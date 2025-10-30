# app.py — In-Room Prioritization (Supabase)
# - 5 votes per person (per device/session)
# - One vote per initiative (toggle Vote/Unvote)
# - Mobile-friendly one-line voting rows
# - Live results without flicker

import os, uuid, time
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization")
st.caption("Vote up to 5 times per person. One vote per initiative. Toggle to unvote. Live results with no flicker.")

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

# Track which initiative IDs this viewer has voted for (per device/session)
if "voted_ids" not in st.session_state:
    st.session_state.voted_ids = set()

# ---------- Data access ----------
def fetch_df_raw() -> pd.DataFrame:
    res = sb.table("initiatives").select("*").order("inserted_at").execute()
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
    # Requires dec_vote(row_id uuid) RPC in Supabase (see SQL below)
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

# ---------- Voting section (flat, one line per item; sorted by votes) ----------
remaining = MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)
remaining = max(0, remaining)
st.subheader(f"All initiatives · Votes remaining: {remaining}")

df_list = fetch_df_raw()

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    # Sort by votes desc, then name asc
    df_list = df_list.sort_values(by=["votes", "initiative"], ascending=[False, True]).reset_index(drop=True)

    for _, row in df_list.iterrows():
        item_id = str(row["id"])
        name    = str(row.get("initiative","(untitled)"))
        cat     = str(row.get("category","Other"))
        vts     = int(row.get("votes", 0))

        # One-line layout: name | category + ⭐votes | button
        c1, c2, c3 = st.columns([7, 3, 2])
        # Keep text concise to help mobile stay on one line
        c1.markdown(f"**{name}**")
        c2.markdown(f"{cat} · ⭐ **{vts}**")

        already_voted = item_id in st.session_state.voted_ids
        label = "Unvote" if already_voted else "⬆️ Vote"
        disabled = False if already_voted else (remaining <= 0)

        if c3.button(label, key=f"vote-toggle-{item_id}", disabled=disabled):
            if already_voted:
                # Unvote: decrement in DB and remove from session
                try:
                    dec_vote(item_id)
                finally:
                    st.session_state.voted_ids.discard(item_id)
                st.toast(f"Removed vote. {MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)} remaining.")
                st.rerun()
            else:
                if remaining <= 0:
                    st.warning("You’ve used all 5 votes on this device.")
                else:
                    try:
                        inc_vote(item_id)
                    finally:
                        st.session_state.voted_ids.add(item_id)
                    st.toast(f"Vote recorded. {MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)} remaining.")
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
    # Table: Initiative | Category | Votes (no updated_at)
    df = df_in.copy()
    df = df.sort_values(by=["votes","initiative"], ascending=[False, True])
    show = [c for c in ["initiative","category","votes"] if c in df.columns]
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

st.caption("Note: Vote limit is enforced per device/session. For stricter per-person limits across devices, add auth and server-side checks in Supabase.")
