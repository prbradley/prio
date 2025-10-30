# app.py — In-Room Prioritization (Supabase) — simple list + 5-vote cap + live results

import os, uuid, time
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization")
st.caption("Add initiatives, vote up to 5 times per person. Live results with no flicker.")

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

# Initialize session vote counter
if "votes_cast" not in st.session_state:
    st.session_state.votes_cast = 0

# ---------- Data access ----------
def fetch_df_raw() -> pd.DataFrame:
    """Read all initiatives ordered by insert time."""
    res = sb.table("initiatives").select("*").order("inserted_at").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        df = pd.DataFrame(columns=[
            "id","initiative","category","votes","inserted_at","updated_at"
        ])
    # Ensure expected columns exist
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
    # Uses your Supabase SQL RPC: inc_vote(row_id uuid)
    sb.rpc("inc_vote", {"row_id": row_id}).execute()

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

# ---------- Voting section (flat list, sorted by votes) ----------
st.subheader(f"All initiatives · Votes remaining: {MAX_VOTES_PER_PERSON - st.session_state.votes_cast}")
remaining = max(0, MAX_VOTES_PER_PERSON - st.session_state.votes_cast)
vote_disabled = remaining <= 0

df_list = fetch_df_raw()

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    # Always show everything; sort by votes desc, then most recently updated
    df_list = df_list.sort_values(by=["votes", "updated_at"], ascending=[False, False]).reset_index(drop=True)

    for _, row in df_list.iterrows():
        name = str(row.get("initiative", "(untitled)"))
        cat  = str(row.get("category", "Other"))
        vts  = int(row.get("votes", 0))

        # Columns: name | category+votes | vote button | status
        c1, c2, c3, c4 = st.columns([6, 3, 1, 2])
        c1.markdown(f"**{name}**")
        c2.markdown(f"_Category:_ **{cat}** &nbsp;·&nbsp; ⭐ **{vts}**")

        # Vote button
        if c3.button("⬆️ Vote", key=f"vote-{row['id']}", disabled=vote_disabled):
            if st.session_state.votes_cast < MAX_VOTES_PER_PERSON:
                inc_vote(row["id"])
                st.session_state.votes_cast += 1
                st.toast(f"Vote recorded. {MAX_VOTES_PER_PERSON - st.session_state.votes_cast} remaining.")
                st.rerun()
            else:
                st.warning("You’ve used all 5 votes on this device.")

        # Disabled indicator when out of votes
        if vote_disabled:
            c4.write("🚫 No votes left")

st.divider()

# ---------- Live Results (flicker-free placeholder updates) ----------
st.subheader("Live Results")

# Toggle to pause live refresh if needed
if "live_mode" not in st.session_state:
    st.session_state.live_mode = True
st.session_state.live_mode = st.toggle("Live mode (1s updates)", value=st.session_state.live_mode)

placeholder = st.empty()

def render_results(df_in: pd.DataFrame):
    if df_in.empty:
        with placeholder.container():
            st.info("No initiatives yet.")
        return
    # Simple leaderboard = sort by votes desc, then updated_at desc
    df = df_in.copy()
    df = df.sort_values(by=["votes","updated_at"], ascending=[False, False])
    show = ["initiative","category","votes","updated_at"]
    show = [c for c in show if c in df.columns]
    with placeholder.container():
        st.dataframe(df[show], use_container_width=True, hide_index=True)

# Initial static paint
render_results(df_list)

# Gentle 1s live loop: only redraws the results table (no buttons inside)
if st.session_state.live_mode:
    start = time.time()
    max_seconds = 120  # safety cap; toggle off/on to continue, or increase
    while time.time() - start < max_seconds:
        time.sleep(1)
        render_results(fetch_df_raw())
else:
    render_results(fetch_df_raw())

# ---------- Export (single widget per run) ----------
latest = fetch_df_raw()
if not latest.empty:
    latest = latest.sort_values(by=["votes","updated_at"], ascending=[False, False])
    present = [c for c in ["initiative","category","votes","updated_at"] if c in latest.columns]
    csv_bytes = latest[present].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download Results (CSV)",
        data=csv_bytes,
        file_name="prioritization_results.csv",
        mime="text/csv",
        key="dl-results",
    )

st.caption("Note: Vote limit is enforced per device/session. For stricter controls, add auth and per-user tracking in Supabase.")
