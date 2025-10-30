# app.py — Prioritization (Supabase)
# - 5 votes per person (per device/session)
# - One vote per initiative (toggle via checkbox)
# - Voting table: Initiative | Category | Your vote (no counts)
# - Results table: Initiative | Category | Votes
# - Live results without flicker; stable order in voting section
# - Mobile-friendly rows; read-only text columns; vote cap persists across reloads

import os, uuid, time
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="Prioritization", layout="wide")
st.markdown(
    "<h1 style='display: flex; align-items: center; gap: 0.5rem;'>🏔️ Prioritization</h1>",
    unsafe_allow_html=True,
)
st.caption("Add initiatives, vote up to 5 times.")

# Compact, single-line rows on mobile for data editor
st.markdown("""
<style>
/* Keep cells on a single line and tighten padding for compact mobile view */
[data-testid="stDataFrame"] table tbody tr td,
[data-testid="stDataFrame"] table thead tr th {
  white-space: nowrap;
}
@media (max-width: 640px) {
  [data-testid="stDataFrame"] table td,
  [data-testid="stDataFrame"] table th {
    padding: 4px 6px !important;
    font-size: 0.95rem !important;
  }
}
</style>
""", unsafe_allow_html=True)

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
    "Change Fatigue","Unclear Accountabilities","Prioritization",
    "Communication","Culture","Cross Functional Friction","Other"
]

# Session state: which initiative IDs this viewer has voted for
if "voted_ids" not in st.session_state:
    st.session_state.voted_ids = set()

# Restore votes from URL query param on first load (persists across refresh)
qs = st.experimental_get_query_params()
if "v" in qs and isinstance(qs["v"], list) and qs["v"]:
    if not st.session_state.voted_ids:
        ids = [i for i in qs["v"][0].split(",") if i]
        st.session_state.voted_ids = set(ids)

def _save_votes_to_url():
    # Store voted ids in the URL so refresh doesn't reset the session cap
    v = ",".join(st.session_state.voted_ids)
    st.experimental_set_query_params(v=v)

# ---------- Data access ----------
def fetch_df_raw() -> pd.DataFrame:
    # Stable order for the voting section: first-in stays first (no reordering)
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
    # update public.initiatives set votes = greatest(coalesce(votes,0)-1,0) where id=row_id;
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
    view = df_list[["initiative","category"]].copy()
    view["Your vote"] = df_list["id"].apply(lambda x: x in st.session_state.voted_ids)
    view.index = df_list["id"]  # stable row identity

    edited = st.data_editor(
        view,
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        disabled=["initiative","category"],  # lock text columns; only checkbox is editable
        column_config={
            "initiative": st.column_config.TextColumn("Initiative", width="medium"),
            "category": st.column_config.TextColumn("Category", width="small"),
            "Your vote": st.column_config.CheckboxColumn(
                "Vote",
                help="Select up to 5. Unselect one to choose another.",
            ),
        },
        column_order=["initiative","category","Your vote"],
    )

    # Enforce: max 5 total selections strictly BEFORE applying any DB change
    current_selected = set(st.session_state.voted_ids)
    edited_selected  = {rid for rid, r in edited.iterrows() if bool(r["Your vote"])}

    newly_selected   = edited_selected - current_selected
    newly_deselected = current_selected - edited_selected

    # If user tries to add beyond the cap, ignore and revert immediately
    if len(current_selected) + len(newly_selected) - len(newly_deselected) > MAX_VOTES_PER_PERSON:
        st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
        _save_votes_to_url()
        st.rerun()

    # Apply allowed changes (DB + session)
    changed = False
    for rid in newly_selected:
        try:
            inc_vote(rid)
        finally:
            st.session_state.voted_ids.add(rid)
        changed = True

    for rid in newly_deselected:
        try:
            dec_vote(rid)
        finally:
            st.session_state.voted_ids.discard(rid)
        changed = True

    if changed:
        _save_votes_to_url()
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
    # Sorting here doesn't affect the voting section order
    df = df.sort_values(by=["votes","initiative"], ascending=[False, True])
    show = ["initiative","category","votes"]
    with placeholder.container():
        st.dataframe(df[show], use_container_width=True, hide_index=True)

# Initial paint
render_results(df_list)

# Live loop updates only the results table (no widget duplication)
if st.session_state.live_mode:
    start = time.time()
    max_seconds = 600  # 10 minutes; adjust as desired
    while time.time() - start < max_seconds:
        time.sleep(1)
        render_results(fetch_df_raw())
else:
    render_results(fetch_df_raw())

# ---------- Export ----------
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
