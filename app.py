# app.py — Prioritization (Supabase)
# - 5 votes per person (per device/session)
# - One vote per initiative (toggle via checkbox)
# - Immediate validation & rollback on 6th vote (no waiting)
# - Stable order, live results, mobile-friendly-ish rows

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

# Light CSS to tighten spacing on small screens
st.markdown("""
<style>
.row { display:flex; align-items:center; gap:.5rem; padding:.25rem 0; }
.row .name { flex: 1 1 auto; font-weight: 600; min-width: 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.row .meta { flex: 0 0 auto; opacity:.8; white-space:nowrap;}
.row .chk  { flex: 0 0 auto; }
@media (max-width:640px){ .row { gap:.35rem; } }
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
    # Requires this RPC in Supabase:
    # create or replace function public.dec_vote(row_id uuid) returns void language sql as $$
    #   update public.initiatives set votes = greatest(coalesce(votes,0)-1,0) where id = row_id;
    # $$;
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

# ---------- Voting (checkbox per row with immediate validation) ----------
df_list = fetch_df_raw()

# Initialize per-row checkbox state to reflect current session votes
for _, r in df_list.iterrows():
    key = f"vote-{r['id']}"
    if key not in st.session_state:
        st.session_state[key] = (r["id"] in st.session_state.voted_ids)

# Header with dynamic remaining (derived from session)
remaining = MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)
remaining = max(0, remaining)
st.subheader(f"All initiatives · Votes remaining: {remaining}")

if df_list.empty:
    st.info("No initiatives yet. Add one above.")
else:
    # Render each row manually to control behavior precisely
    for _, r in df_list.iterrows():
        item_id = str(r["id"])
        key = f"vote-{item_id}"
        checked = st.session_state.get(key, item_id in st.session_state.voted_ids)

        # Row layout with HTML + a Streamlit checkbox right after it
        st.markdown(f"""
        <div class="row">
          <div class="name">{r.get('initiative','(untitled)')}</div>
          <div class="meta">{r.get('category','Other')}</div>
          <div class="chk"></div>
        </div>
        """, unsafe_allow_html=True)

        # Place checkbox (right-justified) – will trigger a rerun on change
        new_val = st.checkbox("Vote", key=key, value=checked)

        # Handle state transition
        if new_val != checked:
            # User toggled this checkbox
            if new_val:  # attempting to add a vote
                if item_id in st.session_state.voted_ids:
                    # Already voted for this (shouldn't happen, but guard)
                    st.session_state[key] = True
                elif len(st.session_state.voted_ids) >= MAX_VOTES_PER_PERSON:
                    # Over the cap: immediately roll back and warn
                    st.session_state[key] = False
                    st.warning("You’ve reached the 5-vote limit. Unselect one to choose another.")
                    st.experimental_rerun()
                else:
                    # OK to add
                    try:
                        inc_vote(item_id)
                    finally:
                        st.session_state.voted_ids.add(item_id)
                        # keep checkbox True; no rerun needed
            else:  # unvoting
                if item_id in st.session_state.voted_ids:
                    try:
                        dec_vote(item_id)
                    finally:
                        st.session_state.voted_ids.discard(item_id)
                        # keep checkbox False; no rerun needed

    # Update remaining label after processing this pass
    remaining = MAX_VOTES_PER_PERSON - len(st.session_state.voted_ids)
    remaining = max(0, remaining)
    st.write(f"**Votes remaining: {remaining}**")

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
