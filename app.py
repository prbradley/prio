# app.py — Prioritization (Supabase)
# - One big, full-width button per initiative (mobile-friendly)
# - Soft green selected state, warm neutral unselected state
# - 5 votes per person (per device/session), toggle to unvote
# - Live results below

import os, uuid, time
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="Prioritization", layout="wide")
st.markdown(
    "<h1 style='display:flex;align-items:center;gap:.5rem;'>🏔️ Prioritization</h1>",
    unsafe_allow_html=True,
)
st.caption("Add initiatives, vote up to 5 times.")

# ---------- Styling (softer neutrals, green highlight) ----------
st.markdown("""
<style>
:root { --primary-color: #16a34a; } /* force green */

/* Selected (primary) buttons: soft emerald gradient */
button[kind="primary"], [data-testid="baseButton-primary"] {
  background: linear-gradient(180deg, #d1fae5 0%, #a7f3d0 100%) !important;
  color: #064e3b !important;
  border: 1px solid #6ee7b7 !important;
}
button[kind="primary"]:hover, [data-testid="baseButton-primary"]:hover {
  background: linear-gradient(180deg, #a7f3d0 0%, #86efac 100%) !important;
  border-color: #34d399 !important;
}

/* Unselected (secondary) buttons: soft neutral beige-gray */
button[kind="secondary"], [data-testid="baseButton-secondary"] {
  background: linear-gradient(180deg, #f9fafb 0%, #f3f4f6 100%) !important;
  color: #1f2937 !important; /* dark gray text */
  border: 1px solid #e5e7eb !important;
}
button[kind="secondary"]:hover, [data-testid="baseButton-secondary"]:hover {
  background: linear-gradient(180deg, #f3f4f6 0%, #e5e7eb 100%) !important;
  border-color: #d1d5db !important;
}

/* Layout / typography */
.stButton > button {
  width: 100% !important;
  text-align: left !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  padding: .75rem .9rem !important;
  font-weight: 600;
  border-radius: 0.5rem !important;
}
.stButton { margin-bottom: .4rem; }
@media (max-width: 640px) {
  .block-container { padding-top: .5rem; padding-left: .75rem; padding-right: .75rem; }
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

# ---------- Session ----------
if "voted_ids" not in st.session_state:
    st.session_state.voted_ids = set()
if "df_list" not in st.session_state:
    st.session_state.df_list = pd.DataFrame(columns=["id","initiative","category","votes"])

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

# ---------- First load ----------
if st.session_state.df_list.empty:
    st.session_state.df_list = fetch_df_raw()

# ---------- Add initiative ----------
st.subheader("Add an initiative")
c1, c2, c3 = st.columns([5, 3, 1])
new_name = c1.text_input("Initiative name", placeholder="e.g., Improve handoffs between eComm and Retail")
new_cat  = c2.selectbox("Category", CATEGORIES, index=CATEGORIES.index("Other"))
if c3.button("Add"):
    if new_name.strip():
        add_initiative(new_name.strip(), new_cat)
        st.session_state.df_list = fetch_df_raw()
        st.success(f"Added to {new_cat}.")
        st.rerun()
    else:
        st.warning("Please enter an initiative name.")

st.divider()

# ---------- Voting (name only) ----------
df_list = st.session_state.df_list
remaining = max(0, MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids))
st.subheader(f"All initiatives · Votes remaining: {remaining}")

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    for _, r in df_list.iterrows():
        item_id = str(r["id"])
        selected = (item_id in st.session_state.voted_ids)
        label = str(r.get("initiative", "(untitled)")).strip() or "(untitled)"

        clicked = st.button(
            label,
            key=f"btn-{item_id}",
            type=("primary" if selected else "secondary"),
            use_container_width=True,
        )

        if clicked:
            if selected:
                try:
                    dec_vote(item_id)
                finally:
                    st.session_state.voted_ids.discard(item_id)
                st.rerun()
            else:
                if len(st.session_state.voted_ids) >= MAX_VOTES_PER_PERSON:
                    st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
                else:
                    try:
                        inc_vote(item_id)
                    finally:
                        st.session_state.voted_ids.add(item_id)
                    st.rerun()

remaining = max(0, MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids))
st.write(f"**Votes remaining: {remaining}**")

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
    with placeholder.container():
        st.dataframe(df[["initiative","category","votes"]], use_container_width=True, hide_index=True)

render_results(df_list)
if st.session_state.live_mode:
    start = time.time()
    while time.time() - start < 600:
        time.sleep(1)
        fresh = fetch_df_raw()
        st.session_state.df_list = fresh
        render_results(fresh)

# ---------- Export ----------
latest = st.session_state.df_list if not st.session_state.df_list.empty else fetch_df_raw()
if not latest.empty:
    latest = latest.sort_values(by=["votes","initiative"], ascending=[False, True])
    csv_bytes = latest[["initiative","category","votes"]].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download Results (CSV)", data=csv_bytes,
                       file_name="prioritization_results.csv", mime="text/csv", key="dl-results")

st.caption("Vote cap is enforced per device/session. For per-user enforcement across devices, add auth and server-side checks.")
