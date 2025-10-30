# app.py — Prioritization (Supabase)
# - 5 votes per person (per device/session)
# - One vote per initiative (toggle via checkbox, immediate validation)
# - Voting list: Initiative | Category | [Vote]
# - Results table: Initiative | Category | Votes
# - Live results; stable order; mobile-tighter rows

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

# Tighten row spacing a bit
st.markdown("""
<style>
.vote-row { display:flex; align-items:center; gap:.5rem; padding:.25rem 0; }
.vote-name { font-weight:600; flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.vote-cat  { flex:0 0 auto; opacity:.8; white-space:nowrap; }
.vote-box  { flex:0 0 auto; }
@media (max-width:640px){ .vote-row{ gap:.35rem; } }
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

# ---------- Data ----------
def fetch_df_raw() -> pd.DataFrame:
    res = sb.table("initiatives").select("*").order("inserted_at", desc=False).execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id","initiative","category","votes"])
    df["category"] = df.get("category", "Other")
    df["votes"] = pd.to_numeric(df.get("votes", 0), errors="coerce").fillna(0).astype(int)
    return df

def add_initiative(name: str, category: str):
    sb.table("initiatives").insert({
        "id": str(uuid.uuid4()),
        "initiative": name,
        "category": category,
        "votes": 0
    }).execute()

def inc_vote(item_id: str):
    sb.rpc("inc_vote", {"row_id": item_id}).execute()

def dec_vote(item_id: str):
    sb.rpc("dec_vote", {"row_id": item_id}).execute()

# ---------- Add initiative ----------
st.subheader("Add an initiative")
c1, c2, c3 = st.columns([5, 3, 1])
new_name = c1.text_input("Initiative name", placeholder="e.g., Improve handoffs between eComm and Retail")
new_cat  = c2.selectbox("Category", CATEGORIES, index=CATEGORIES.index("Other"))
if c3.button("Add"):
    if new_name.strip():
        add_initiative(new_name.strip(), new_cat)
        st.success(f"Added to {new_cat}.")
        st.rerun()
    else:
        st.warning("Please enter an initiative name.")

st.divider()

# ---------- Voting (checkbox per row with callback) ----------
df_list = fetch_df_raw()

# Initialize widget state from session on first render
for _, r in df_list.iterrows():
    key = f"cb-{r['id']}"
    if key not in st.session_state:
        st.session_state[key] = (r["id"] in st.session_state.voted_ids)

def handle_toggle(item_id: str, key: str):
    """Runs on each checkbox change; enforces limits and updates DB+session."""
    new_val = st.session_state[key]

    # If turning ON
    if new_val:
        # Already counted? nothing to do
        if item_id in st.session_state.voted_ids:
            return
        # Hitting the cap? revert and warn
        if len(st.session_state.voted_ids) >= MAX_VOTES_PER_PERSON:
            st.session_state[key] = False  # flip it back off immediately
            st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
            return
        # OK to add
        try:
            inc_vote(item_id)
        finally:
            st.session_state.voted_ids.add(item_id)
        return

    # If turning OFF
    if item_id in st.session_state.voted_ids:
        try:
            dec_vote(item_id)
        finally:
            st.session_state.voted_ids.remove(item_id)

# Header — compute from session (updated by the callback above instantly)
remaining = MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)
remaining = max(0, remaining)
st.subheader(f"All initiatives · Votes remaining: {remaining}")

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    # Render stable rows (no reordering)
    for _, r in df_list.iterrows():
        item_id = str(r["id"])
        key = f"cb-{item_id}"

        # Row text
        st.markdown(
            f"<div class='vote-row'>"
            f"<div class='vote-name'>{r.get('initiative','(untitled)')}</div>"
            f"<div class='vote-cat'>{r.get('category','Other')}</div>"
            f"</div>",
            unsafe_allow_html=True
        )
        # Checkbox right below the row text; uses callback to enforce logic
        st.checkbox(
            "Vote",
            key=key,
            value=st.session_state[key],
            on_change=handle_toggle,
            args=(item_id, key),
        )

st.divider()

# ---------- Live Results ----------
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
    df = df_in.copy().sort_values(by=["votes","initiative"], ascending=[False, True])
    cols = ["initiative","category","votes"]
    with placeholder.container():
        st.dataframe(df[cols], use_container_width=True, hide_index=True)

render_results(df_list)

if st.session_state.live_mode:
    start = time.time()
    while time.time() - start < 600:  # 10 minutes; adjust as needed
        time.sleep(1)
        render_results(fetch_df_raw())

# ---------- Export ----------
latest = fetch_df_raw()
if not latest.empty:
    latest = latest.sort_values(by=["votes","initiative"], ascending=[False, True])
    csv_bytes = latest[["initiative","category","votes"]].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download Results (CSV)", data=csv_bytes,
                       file_name="prioritization_results.csv", mime="text/csv", key="dl-results")

st.caption("Vote cap is enforced per device/session. For per-user enforcement across devices, add auth and server-side checks.")
