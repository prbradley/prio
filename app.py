# app.py — In-Room Prioritization (Supabase)
# - 5 votes per person (per device/session)
# - One vote per initiative (toggle via table checkbox)
# - Voting table: Initiative | Category | Your vote (no counts)
# - Results table: Initiative | Category | Votes
# - Live results without flicker; stable order in voting section

import os, uuid, time
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization")
st.caption("Vote up to 5 times per person. One vote per initiative. Toggle to unvote. Live results without flicker.")

# ---------- Secrets / clients ----------
SB_URL = st.secrets.get("SUPABASE_URL")
SB_KEY = st.secrets.get("SUPABASE_ANON_KEY")
if not SB_URL or not SB_KEY:
    st.error("Missing SUPABASE_URL or SUPABASE_ANON_KEY in Streamlit secrets.")
    st.stop()
sb: Client = create_client(SB_URL, SB_KEY)

# ---------- Config ----------
MAX_VOTES_PER_PERSON = 5
CATEGORIES = [
    "Operating Model","Change Fatigue","Unclear Accountabilities","Prioritization",
    "Communication","Culture","Cross Functional Friction","Other"
]

# Session state: which initiative IDs this viewer has voted for
if "voted_ids" not in st.session_state:
    st.session_state.voted_ids = set()

# ---------- Data access ----------
def fetch_df_raw() -> pd.DataFrame:
    # Keep stable order for the voting section: first-in stays first (no reordering)
    res = sb.table("initiatives").select("*").order("inserted_at", desc=False).execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        df = pd.DataFrame(columns=["id","initiative","category","votes"])
    if "category" not in df.columns:
        df["category"] = "Other"
    if "votes" not in df.columns:
        df["votes"] = 0
    return df

def add_initiative(name: str, category: str):
    row = {
        "id": str(uuid.uuid4()),
        "initiative": name,
        "category": category,
        "votes": 0
    }
    sb.table("initiatives").insert(row).execute()

def inc_vote(row_id: str):
    sb.rpc("inc_vote", {"row_id": row_id}).execute()

def dec_vote(row_id: str):
    # Requires dec_vote(row_id uuid) RPC in Supabase:
    #   update public.initiatives set votes = greatest(coalesce(votes,0)-1,0) where id=row_id;
    sb.rpc("dec_vote", {"row_id": row_id}).execute()

# ---------- Add initiative (always visible: name + category) ----------
st.subheader("Add an initiative")
col_name, col_cat, col_btn = st.columns([5, 3, 1])
new_name = col_name.text_input("Initiative name", placeholder="e.g., Improve handoffs between eComm and Retail")
new_cat = col_cat.selectbox("Category", CATEGORIES, index=CATEGORIES.index("Other"))
if col_btn.button("Add"):
    if new_name.strip():
        add_initiative(new_name.strip(), new_cat)
        st.success(f"Added to {new_cat}.")
        st.rerun()
    else:
        st.warning("Please enter an initiative name.")

st.divider()

# ---------- Voting section (table; fixed order; one-line per item; NO vote counts) ----------
df_list = fetch_df_raw()
remaining = MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)
remaining = max(0, remaining)
st.subheader(f"All initiatives · Votes remaining: {remaining}")

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    # Build a table-like editor with a boolean "Your vote" column.
    # Index by initiative id to track toggles reliably without reordering.
    view = df_list[["initiative","category"]].copy()
    view["Your vote"] = df_list["id"].apply(lambda x: x in st.session_state.voted_ids)
    view.index = df_list["id"]  # stable row identity

    edited = st.data_editor(
        view,
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        column_config={
            "initiative": st.column_config.TextColumn("Initiative", width="medium"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "Your vote": st.column_config.CheckboxColumn(
                "Vote",
                help="Select up to 5. Unselect one to free a vote.",
            ),
        },
        column_order=["initiative","category","Your vote"],
    )

    # Enforce: max 5 total selections; 1 per initiative; allow unvote
    changed = False
    # Count intended total selections in the edited table
    intended_selected_ids = {rid for rid, r in edited.iterrows() if bool(r["Your vote"])}
    # If user tried to push beyond cap, revert by restoring session's allowed state
    if len(intended_selected_ids) > MAX_VOTES_PER_PERSON:
        st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
        # Repaint to the canonical state without applying any DB changes
        st.rerun()

    # Apply diffs (DB + session) within the cap
    for row_id, row in edited.iterrows():
        new_mark = bool(row["Your vote"])
        was_mark = (row_id in st.session_state.voted_ids)

        if new_mark and not was_mark:
            # adding a vote
            if len(st.session_state.voted_ids) >= MAX_VOTES_PER_PERSON:
                # refuse and revert
                st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
                changed = True
                st.rerun()
            try:
                inc_vote(row_id)
            finally:
                st.session_state.voted_ids.add(row_id)
            changed = True

        elif (not new_mark) and was_mark:
            # removing a vote
            try:
                dec_vote(row_id)
            finally:
                st.session_state.voted_ids.discard(row_id)
            changed = True

    if changed:
        st.rerun()

st.divider()

# ---------- Live Results (flicker-free placeholder updates) ----------
st.subheader("Live Results")

if "live_mode" not in st.session_state:
    st.session_state.live_mode = True
st.session_state.live_mode = st.toggle("Live mode (1s updates)", value=st.session_state.live_mode)

placeholder = st.empty()

def render_results(df_in: pd.DataFrame):
    if df_in.empty:
        with placeholder.container():
            st.info("No initiatives yet.")
        return
    # Results table: Initiative | Category | Votes
    df = df_in.copy()
    df = df.sort_values(by=["votes","initiative"], ascending=[False, True])
    show = ["initiative","category","votes"]
    with placeholder.container():
        st.dataframe(df[show], use_container_width=True, hide_index=True)

# Initial paint
render_results(df_list)

# Live loop updates only the results table (no widget duplication)
if st.session_state.live_mode:
    start = time.time()
    max_seconds = 120
    while time.time() - start < max_seconds:
        time.sleep(1)
        render_results(fetch_df_raw())
else:
    render_results(fetch_df_raw())

# ---------- Export (single widget per run) ----------
latest = fetch_df_raw()
if not latest.empty:
    latest = latest.sort_values(by=["votes","initiative"], ascending=[False, True])
    present = [c for c in ["initiative","category","votes"] if c in latest.columns]
    csv_bytes = latest[present].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Results (CSV)",
        data=csv_bytes,
        file_name="prioritization_results.csv",
        mime="text/csv",
        key="dl-results",
    )

st.caption("Vote cap is enforced per device/session. For per-user enforcement across devices, add auth and server-side checks.")
