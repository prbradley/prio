import os, uuid, time, json
import pandas as pd
import streamlit as st
from supabase import create_client, Client
from openai import OpenAI

st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization (Supabase)")
st.caption("Shared backend so everyone sees the same data. Rate → Vote → Live ranking.")

# ---------------- Config & Clients ----------------
SB_URL = st.secrets.get("SUPABASE_URL")
SB_KEY = st.secrets.get("SUPABASE_ANON_KEY")
sb: Client = create_client(SB_URL, SB_KEY)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DEFAULT_WEIGHTS = {"Impact": 0.4, "Alignment": 0.35, "Effort": -0.15, "Risk": -0.10}
st.sidebar.header("Weights")
w_impact   = st.sidebar.slider("Impact weight",   0.0, 1.0, DEFAULT_WEIGHTS["Impact"], 0.05)
w_align    = st.sidebar.slider("Alignment weight",0.0, 1.0, DEFAULT_WEIGHTS["Alignment"], 0.05)
w_effort   = st.sidebar.slider("Effort weight",  -1.0, 0.0, DEFAULT_WEIGHTS["Effort"], 0.05)
w_risk     = st.sidebar.slider("Risk weight",    -1.0, 0.0, DEFAULT_WEIGHTS["Risk"], 0.05)
WEIGHTS = {"Impact": w_impact, "Alignment": w_align, "Effort": w_effort, "Risk": w_risk}

# Simple polling so all devices refresh every ~2s
st.markdown("<meta http-equiv='refresh' content='2'>", unsafe_allow_html=True)

# ---------------- Data Access ----------------
def fetch_df() -> pd.DataFrame:
    res = sb.table("initiatives").select("*").order("inserted_at").execute()
    df = pd.DataFrame(res.data or [])
    if df.empty:
        df = pd.DataFrame(columns=[
            "id","initiative","description","owner","category",
            "impact","alignment","effort","risk","votes","cluster",
            "inserted_at","updated_at"
        ])
    return df

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
    sb.rpc("inc_vote", {"row_id": row_id}).execute()

def set_cluster(row_id, label):
    sb.table("initiatives").update({"cluster": label}).eq("id", row_id).execute()

# ---------------- Optional AI clustering ----------------
def ai_cluster(labels):
    if not client or not labels:
        return {}
    prompt = f"""
Group similar initiatives (exact names below) into up to 7 clusters.
Return JSON: {{"clusters":[{{"label":"string","items":["exact initiative name"]}}]}}
List:
{chr(10).join(labels)}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.2,
    )
    try:
        j = json.loads(resp.choices[0].message.content)
        mapping = {}
        for cl in j.get("clusters", []):
            label = cl.get("label","Cluster")
            for item in cl.get("items", []):
                mapping[item] = label
        return mapping
    except Exception:
        return {}

# ---------------- Upload (optional seeding) ----------------
with st.expander("📥 Seed from CSV (optional)"):
    st.caption("Upload once; rows will be inserted into Supabase.")
    up = st.file_uploader("CSV with columns: Initiative, Short Description, Owner / Team, Category (Run / CI / Strategic)", type=["csv"])
    if up and st.button("Insert CSV rows"):
        seed = pd.read_csv(up).fillna("")
        for _, r in seed.iterrows():
            add_initiative(
                r.get("Initiative","").strip(),
                r.get("Short Description","").strip(),
                r.get("Owner / Team","").strip(),
                r.get("Category (Run / CI / Strategic)","Other").strip()
            )
        st.success("Inserted.")

# ---------------- Add initiative ----------------
with st.expander("➕ Add initiative"):
    c1,c2 = st.columns([3,2])
    name = c1.text_input("Initiative")
    owner = c2.text_input("Owner / Team")
    desc = st.text_area("Short Description")
    cat = st.selectbox("Category", ["Run","CI","Strategic","Other"])
    if st.button("Add"):
        if name.strip():
            add_initiative(name.strip(), desc.strip(), owner.strip(), cat)
            st.success("Added.")

# ---------------- Cluster (optional) ----------------
c1,c2 = st.columns([1,3])
if c1.button("🤖 Cluster similar items"):
    df_now = fetch_df()
    names = df_now["initiative"].astype(str).tolist()
    cmap = ai_cluster(names)
    if cmap:
        for _, r in df_now.iterrows():
            lab = cmap.get(str(r["initiative"]), "")
            if lab:
                set_cluster(r["id"], lab)
        st.success("Clustered.")
    else:
        st.info("No clusters (or OpenAI key not set).")

# ---------------- Rate & Vote ----------------
st.subheader("Rate & Vote")
df = fetch_df()

if df.empty:
    st.info("No initiatives yet. Add one above or seed from CSV.")
else:
    for _, row in df.iterrows():
        with st.expander(f"📌 {row.get('initiative','(untitled)')}"):
            c1,c2,c3,c4,c5 = st.columns([2,1,1,1,1])
            c1.write(row.get("description",""))
            impact  = c2.number_input("Impact (1-5)",   1, 5, int(row["impact"]) if pd.notna(row["impact"]) else 3, key=f"imp-{row['id']}")
            align   = c3.number_input("Alignment (1-5)",1, 5, int(row["alignment"]) if pd.notna(row["alignment"]) else 3, key=f"aln-{row['id']}")
            effort  = c4.number_input("Effort (1-5)",   1, 5, int(row["effort"]) if pd.notna(row["effort"]) else 3, key=f"eff-{row['id']}")
            risk    = c5.number_input("Risk (1-5)",     1, 5, int(row["risk"]) if pd.notna(row["risk"]) else 3, key=f"rsk-{row['id']}")

            col_a, col_b = st.columns([1,9])
            if col_a.button("💾 Save", key=f"save-{row['id']}"):
                update_ratings(row["id"], impact, align, effort, risk)
                st.toast("Saved")

            if col_a.button("⬆️ Vote", key=f"vote-{row['id']}-btn"):
                inc_vote(row["id"])
                st.toast("Voted")

# ---------------- Leaderboard ----------------
def score_row(r):
    parts = []
    if pd.notna(r.get("impact")):   parts.append(r["impact"]   * WEIGHTS["Impact"])
    if pd.notna(r.get("alignment")):parts.append(r["alignment"]* WEIGHTS["Alignment"])
    if pd.notna(r.get("effort")):   parts.append(r["effort"]   * WEIGHTS["Effort"])
    if pd.notna(r.get("risk")):     parts.append(r["risk"]     * WEIGHTS["Risk"])
    return sum(parts) if parts else 0.0

df = fetch_df()
if not df.empty:
    df["Score"] = df.apply(score_row, axis=1)
    df = df.sort_values(by=["Score","votes"], ascending=[False,False])

    st.subheader("Live Leaderboard")
    show_cols = [
        "initiative","cluster","impact","alignment","effort","risk","votes","Score",
        "owner","category","updated_at"
    ]
    present = [c for c in show_cols if c in df.columns]
    st.dataframe(df[present], use_container_width=True, hide_index=True)

    st.download_button(
        "⬇️ Download Results (CSV)",
        data=df[present].to_csv(index=False),
        file_name="prioritization_results.csv",
        mime="text/csv"
    )
