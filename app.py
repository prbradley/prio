# app.py — Prioritization (Supabase)
# - One big, full-width button per initiative (mobile-friendly)
# - Soft green shading when selected
# - 5 votes per person (per device/session), 1 per initiative, toggle to unvote
# - Stable order; live results below

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

# ---------- Styling (pleasant selected shading; full-width row buttons) ----------
st.markdown("""
<style>
/* Unselected (secondary) buttons: neutral */
[data-testid="baseButton-secondary"] {
  background: #f3f4f6 !important;     /* gray-100 */
  color: #111827 !important;           /* gray-900 */
  border: 1px solid #e5e7eb !important;/* gray-200 */
}
/* Selected (primary) buttons: soft green gradient + readable text */
[data-testid="baseButton-primary"] {
  background: linear-gradient(180deg, #d1fae5 0%, #a7f3d0 100%) !important; /* emerald-100 -> emerald-200 */
  color: #065f46 !important;            /* emerald-800 */
  border: 1px solid #6ee7b7 !important; /* emerald-300 */
}
[data-testid="baseButton-primary"]:hover {
  background: linear-gradient(180deg, #a7f3d0 0%, #86efac 100%) !important; /* emerald-200 -> emerald-300 */
  border-color: #34d399 !important;     /* emerald-400 */
}
/* Full-width row look; single line with ellipsis */
.stButton > button {
  width: 100% !important;
  text-align: left !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  padding: .75rem .9rem !important;
  font-weight: 600;
}
.stButton { margin-bottom: .35rem; }
/* Tighter container on small screens */
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

# Track which initiative IDs this viewer has voted for
if "voted_ids" not in st.session_state:
    st.session_state.voted_ids = set()

# ---------- Data ----------
def fetch_df_raw() -> pd.DataFrame:
    res = sb.table("initiatives").select("*").order("inserted_at", desc=False).execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id","initiative","category","votes"])
    if "category" not in df.columns: df["category"] = "Other"
    if "votes" not in df.columns: df["votes"] = 0
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce").fillna(0).astype(int)
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
    # Ensure you have this RPC in Supabase:
    # create or replace function public.dec_vote(row_id uuid) returns void language sql as $$
    #   update public.initiatives set votes = greatest(coalesce(votes,0)-1,0) where id=row_id;
    # $$;
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

# ---------- Voting (one big button per initiative) ----------
df_list = fetch_df_raw()

# Header — from session state
remaining = max(0, MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids))
st.subheader(f"All initiatives · Votes remaining: {remaining}")

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    for _, r in df_list.iterrows():
        item_id = str(r["id"])
        selected = (item_id in st.session_state.voted_ids)

        # Full-width button with "Name · Category"
        name = str(r.get("initiative", "(untitled)")).strip() or "(untitled)"
        cat  = str(r.get("category", "Other")).strip() or "Other"
        label = f"{name} · {cat}"

        clicked = st.button(
            label,
            key=f"btn-{item_id}",
            type=("primary" if selected else "secondary"),
            use_container_width=True,
            help="Tap to select/unselect. Max 5 selections.",
        )

        if clicked:
            # Toggle with cap enforcement
            if selected:
                # Unvote
                try:
                    dec_vote(item_id)
                finally:
                    st.session_state.voted_ids.discard(item_id)
                st.rerun()  # repaint now so green state clears
            else:
                if len(st.session_state.voted_ids) >= MAX_VOTES_PER_PERSON:
                    st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
                    # Do not add; leave as unselected
                else:
                    try:
                        inc_vote(item_id)
                    finally:
                        st.session_state.voted_ids.add(item_id)
                    st.rerun()  # repaint now so green state applies

# Recompute and show remaining after any clicks processed
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
    cols = ["initiative","category","votes"]
    with placeholder.container():
        st.dataframe(df[cols], use_container_width=True, hide_index=True)

render_results(df_list)

if st.session_state.live_mode:
    start = time.time()
    while time.time() - start < 600:  # 10 minutes
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
