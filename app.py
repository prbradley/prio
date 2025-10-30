# app.py — In-Room Prioritization (Supabase, flicker-free live updates)

import os, uuid, time, json
import pandas as pd
import streamlit as st
from supabase import create_client, Client

# ---------- Page setup ----------
st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization")
st.caption("Shared Supabase backend. Rate → Vote → Live ranking (no hard refresh flicker).")

# ---------- Secrets / clients ----------
SB_URL = st.secrets.get("SUPABASE_URL")
SB_KEY = st.secrets.get("SUPABASE_ANON_KEY")
if not SB_URL or not SB_KEY:
    st.error("Missing SUPABASE_URL or SUPABASE_ANON_KEY in Streamlit secrets.")
    st.stop()

sb: Client = create_client(SB_URL, SB_KEY)

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
try:
    from openai import OpenAI
    oai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    oai = None  # OpenAI optional (only for clustering)

# ---------- Weights (tweakable) ----------
DEFAULT_WEIGHTS = {"Impact": 0.40, "Alignment": 0.35, "Effort": -0.15, "Risk": -0.10}
st.sidebar.header("Scoring weights")
w_impact = st.sidebar.slider("Impact",   0.0,  1.0, DEFAULT_WEIGHTS["Impact"],   0.05)
w_align  = st.sidebar.slider("Alignment",0.0,  1.0, DEFAULT_WEIGHTS["Alignment"],0.05)
w_effort = st.sidebar.slider("Effort",   -1.0, 0.0, DEFAULT_WEIGHTS["Effort"],   0.05)
w_risk   = st.sidebar.slider("Risk",     -1.0, 0.0, DEFAULT_WEIGHTS["Risk"],     0.05)
WEIGHTS = {"Impact": w_impact, "Alignment": w_align, "Effort": w_effort, "Risk": w_risk}

# ---------- Data access ----------
def _cols():
    return [
        "id","initiative","description","owner","category",
        "impact","alignment","effort","risk","votes","cluster",
        "inserted_at","updated_at"
    ]

def fetch_df_raw() -> pd.DataFrame:
    res = sb.table("initiatives").select("*").order("inserted_at").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        return pd.DataFrame(columns=_cols())
    return df

# cache reads lightly to reduce jitter; we’ll bypass cache when we need a fresh read
@st.cache_data(ttl=0.5)
def fetch_df_cached() -> pd.DataFrame:
    return fetch_df_raw()

def add_initiative(name, desc, owner, category):
    row = {
        "id": str(uuid.uuid4()),
        "initiative": name, "description": desc, "owner": owner,
        "category": category, "impact": None, "alignment": None,
        "effort": None, "risk": None, "votes": 0, "cluster": ""
    }
    sb.table("initiatives").insert(row).execute()

def update_ratings(row_id, impact, alignment, effort, risk):
    sb.table("initiatives").update({
        "impact": int(impact), "alignment": int(alignment),
        "effort": int(effort), "risk": int(risk)
    }).eq("id", row_id).execute()

def inc_vote(row_id):
    # uses the inc_vote RPC you created in Supabase SQL
    sb.rpc("inc_vote", {"row_id": row_id}).execute()

def set_cluster(row_id, label):
    sb.table("initiatives").update({"cluster": label}).eq("id", row_id).execute()

# ---------- Optional AI clustering ----------
def ai_cluster(names: list[str]) -> dict:
    if not oai or not names:
        return {}
    prompt = f"""
Group similar initiatives (exact names below) into up to 7 clusters.
Return JSON only: {{"clusters":[{{"label":"string","items":["exact initiative name"]}}]}}
List:
{chr(10).join([str(n) for n in names])}
"""
    try:
        resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
        mapping = {}
        for c in data.get("clusters", []):
            label = c.get("label", "Cluster")
            for item in c.get("items", []):
                mapping[item] = label
        return mapping
    except Exception:
        return {}

# ---------- Seed from CSV (optional) ----------
with st.expander("📥 Seed from CSV (optional)"):
    st.caption("Columns: Initiative, Short Description, Owner / Team, Category (Run / CI / Strategic)")
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up and st.button("Insert uploaded rows"):
        seed = pd.read_csv(up).fillna("")
        for _, r in seed.iterrows():
            add_initiative(
                r.get("Initiative","").strip(),
                r.get("Short Description","").strip(),
                r.get("Owner / Team","").strip(),
                r.get("Category (Run / CI / Strategic)","Other").strip()
            )
        st.success("Inserted rows into Supabase.")

# ---------- Add initiative ----------
with st.expander("➕ Add initiative"):
    c1, c2 = st.columns([3,2])
    name = c1.text_input("Initiative")
    owner = c2.text_input("Owner / Team")
    desc  = st.text_area("Short Description")
    cat   = st.selectbox("Category", ["Run","CI","Strategic","Other"])
    if st.button("Add"):
        if name.strip():
            add_initiative(name.strip(), desc.strip(), owner.strip(), cat)
            st.success("Added.")
        else:
            st.warning("Please enter an initiative name.")

# ---------- Cluster (optional) ----------
c1, c2 = st.columns([1,3])
if c1.button("🤖 Cluster similar items"):
    current = fetch_df_raw()  # bypass cache for most recent data
    names = current["initiative"].dropna().astype(str).tolist()
    cmap = ai_cluster(names)
    if cmap:
        for _, r in current.iterrows():
            lab = cmap.get(str(r["initiative"]), "")
            if lab:
                set_cluster(r["id"], lab)
        st.success("Clustered.")
    else:
        st.info("No clusters (or OpenAI key not set).")

# ---------- Rating & voting ----------
st.subheader("Rate & Vote")
df_static = fetch_df_cached()
if df_static.empty:
    st.info("No initiatives yet. Add one above or seed from CSV.")
else:
    for _, row in df_static.iterrows():
        with st.expander(f"📌 {row.get('initiative','(untitled)')}"):
            c1, c2, c3, c4, c5 = st.columns([2,1,1,1,1])
            c1.write(row.get("description",""))
            impact = c2.number_input("Impact (1-5)", 1, 5,
                                     int(row["impact"]) if pd.notna(row["impact"]) else 3,
                                     key=f"imp-{row['id']}")
            align  = c3.number_input("Alignment (1-5)", 1, 5,
                                     int(row["alignment"]) if pd.notna(row["alignment"]) else 3,
                                     key=f"aln-{row['id']}")
            effort = c4.number_input("Effort (1-5)", 1, 5,
                                     int(row["effort"]) if pd.notna(row["effort"]) else 3,
                                     key=f"eff-{row['id']}")
            risk   = c5.number_input("Risk (1-5)", 1, 5,
                                     int(row["risk"]) if pd.notna(row["risk"]) else 3,
                                     key=f"rsk-{row['id']}")

            b1, b2 = st.columns([1,9])
            if b1.button("💾 Save", key=f"save-{row['id']}"):
                update_ratings(row["id"], impact, align, effort, risk)
                st.toast("Saved")

            if b1.button("⬆️ Vote", key=f"vote-{row['id']}"):
                inc_vote(row["id"])
                st.toast("Voted")

# ---------- Leaderboard (flicker-free live updates) ----------
def score_row(r):
    s = 0.0
    if pd.notna(r.get("impact")):    s += r["impact"]    * WEIGHTS["Impact"]
    if pd.notna(r.get("alignment")): s += r["alignment"] * WEIGHTS["Alignment"]
    if pd.notna(r.get("effort")):    s += r["effort"]    * WEIGHTS["Effort"]
    if pd.notna(r.get("risk")):      s += r["risk"]      * WEIGHTS["Risk"]
    return s

st.subheader("Live Leaderboard")

# Live mode UI state
if "live_mode" not in st.session_state:
    st.session_state.live_mode = True

st.session_state.live_mode = st.toggle("Live mode (1s updates)", value=st.session_state.live_mode)

placeholder = st.empty()

def render_leaderboard(df_in: pd.DataFrame):
    if df_in.empty:
        with placeholder.container():
            st.info("No initiatives yet.")
        return
    df = df_in.copy()
    df["Score"] = df.apply(score_row, axis=1)
    df = df.sort_values(by=["Score","votes"], ascending=[False, False])
    show_cols = [
        "initiative","cluster","impact","alignment","effort","risk","votes","Score",
        "owner","category","updated_at"
    ]
    present = [c for c in show_cols if c in df.columns]
    with placeholder.container():
        st.dataframe(df[present], use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download Results (CSV)",
            data=df[present].to_csv(index=False),
            file_name="prioritization_results.csv",
            mime="text/csv",
            key="dl-results",
        )

# Initial paint using cached data (fast)
render_leaderboard(fetch_df_cached())

# Gentle polling loop (no hard refresh). Runs for up to 2 minutes at a time so it doesn't block forever.
if st.session_state.live_mode:
    start = time.time()
    max_seconds = 120  # safety cap; un-toggle/re-toggle to continue beyond 2 min
    while time.time() - start < max_seconds:
        time.sleep(1)                # wait 1s
        df_fresh = fetch_df_raw()    # bypass cache for the newest view
        render_leaderboard(df_fresh)
        # If user turns live mode off (on next rerun), loop will not restart.

st.caption("Tip: Live mode only re-renders the leaderboard container, so forms & expanders stay open without flicker.")
