import os, uuid, time, json
import pandas as pd
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="In-Room Prioritization", layout="wide")
st.title("🏔️ In-Room Initiative Prioritization")
st.caption("Rate → Vote → See live ranking. Use 1–5 for ratings. Votes are dot-votes.")

# --- Config ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DEFAULT_WEIGHTS = {"Impact": 0.4, "Alignment": 0.35, "Effort": -0.15, "Risk": -0.10}
st.sidebar.header("Weights")
w_impact   = st.sidebar.slider("Impact weight",   0.0, 1.0, DEFAULT_WEIGHTS["Impact"], 0.05)
w_align    = st.sidebar.slider("Alignment weight",0.0, 1.0, DEFAULT_WEIGHTS["Alignment"], 0.05)
w_effort   = st.sidebar.slider("Effort weight",  -1.0, 0.0, DEFAULT_WEIGHTS["Effort"], 0.05)
w_risk     = st.sidebar.slider("Risk weight",    -1.0, 0.0, DEFAULT_WEIGHTS["Risk"], 0.05)
WEIGHTS = {"Impact": w_impact, "Alignment": w_align, "Effort": w_effort, "Risk": w_risk}

# --- Load data ---
def load_csv(uploaded):
    df = pd.read_csv(uploaded).fillna("")
    if "Votes" not in df.columns:
        df["Votes"] = 0
    # normalize expected columns if user used template
    rename = {
        "Impact (1-5)": "Impact",
        "Strategic Alignment (1-5)": "Alignment",
        "Effort (1-5)": "Effort",
        "Risk (1-5)": "Risk",
    }
    for k,v in rename.items():
        if k in df.columns:
            df.rename(columns={k:v}, inplace=True)
    for col in ["Impact","Alignment","Effort","Risk","Votes"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "id" not in df.columns:
        df["id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    return df

if "data" not in st.session_state:
    st.session_state.data = pd.DataFrame(columns=[
        "id","Initiative","Short Description","Owner / Team","Category (Run / CI / Strategic)",
        "Impact","Alignment","Effort","Risk","Votes","Cluster"
    ])

uploaded = st.file_uploader("Upload initiatives CSV (use the template)", type=["csv"])
if uploaded:
    st.session_state.data = load_csv(uploaded)

# --- Add new initiative (optional in-room) ---
with st.expander("➕ Add an initiative"):
    c1,c2 = st.columns([3,2])
    name = c1.text_input("Initiative")
    owner = c2.text_input("Owner / Team")
    desc = st.text_area("Short Description")
    cat = st.selectbox("Category", ["Run","CI","Strategic","Other"])
    if st.button("Add"):
        if name.strip():
            new = {
                "id": str(uuid.uuid4()),
                "Initiative": name.strip(),
                "Short Description": desc.strip(),
                "Owner / Team": owner.strip(),
                "Category (Run / CI / Strategic)": cat,
                "Impact": None, "Alignment": None, "Effort": None, "Risk": None, "Votes": 0, "Cluster": ""
            }
            st.session_state.data = pd.concat([st.session_state.data, pd.DataFrame([new])], ignore_index=True)
            st.success("Added.")

# --- AI clustering (optional) ---
def ai_cluster(labels):
    if not client:
        st.warning("Set OPENAI_API_KEY to enable clustering.")
        return {}
    prompt = f"""
Group similar initiatives (list below) into up to 7 clusters. 
Return JSON: {{"clusters":[{{"label": "string", "items": ["initiative name exactly"]}}]}}
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

c1,c2 = st.columns([1,3])
if c1.button("🤖 Cluster similar items"):
    names = st.session_state.data["Initiative"].astype(str).tolist()
    cmap = ai_cluster(names)
    if cmap:
        st.session_state.data["Cluster"] = st.session_state.data["Initiative"].map(lambda x: cmap.get(str(x),""))
        st.success("Clustered.")
    else:
        st.info("No clusters or API key missing.")

# --- Ratings & voting ---
st.subheader("Rate & Vote")
for idx, row in st.session_state.data.iterrows():
    with st.expander(f"📌 {row.get('Initiative','(untitled)')}"):
        c1,c2,c3,c4,c5 = st.columns([2,1,1,1,1])
        c1.write(row.get("Short Description",""))
        impact  = c2.number_input("Impact (1-5)",   min_value=1, max_value=5, value=int(row["Impact"]) if pd.notna(row["Impact"]) else 3, key=f"imp-{row['id']}")
        align   = c3.number_input("Alignment (1-5)",min_value=1, max_value=5, value=int(row["Alignment"]) if pd.notna(row["Alignment"]) else 3, key=f"aln-{row['id']}")
        effort  = c4.number_input("Effort (1-5)",   min_value=1, max_value=5, value=int(row["Effort"]) if pd.notna(row["Effort"]) else 3, key=f"eff-{row['id']}")
        risk    = c5.number_input("Risk (1-5)",     min_value=1, max_value=5, value=int(row["Risk"]) if pd.notna(row["Risk"]) else 3, key=f"rsk-{row['id']}")
        st.session_state.data.loc[idx, ["Impact","Alignment","Effort","Risk"]] = [impact,align,effort,risk]
        b1,b2 = st.columns([1,9])
        if b1.button("⬆️ Vote", key=f"vote-{row['id']}"):
            st.session_state.data.loc[idx, "Votes"] = (row["Votes"] or 0) + 1
            time.sleep(0.05)
            st.rerun()

# --- Leaderboard ---
def score(r):
    i,a,e,k = r["Impact"], r["Alignment"], r["Effort"], r["Risk"]
    parts = []
    if pd.notna(i): parts.append(i*WEIGHTS["Impact"])
    if pd.notna(a): parts.append(a*WEIGHTS["Alignment"])
    if pd.notna(e): parts.append(e*WEIGHTS["Effort"])
    if pd.notna(k): parts.append(k*WEIGHTS["Risk"])
    return sum(parts) if parts else 0.0

df = st.session_state.data.copy()
df["Score"] = df.apply(score, axis=1)
df = df.sort_values(by=["Score","Votes"], ascending=[False,False])

st.subheader("Live Leaderboard")
show_cols = ["Initiative","Cluster","Impact","Alignment","Effort","Risk","Votes","Score","Owner / Team","Category (Run / CI / Strategic)"]
present = [c for c in show_cols if c in df.columns]
st.dataframe(df[present], use_container_width=True, hide_index=True)

st.download_button(
    "⬇️ Download Results (CSV)",
    data=df.to_csv(index=False),
    file_name="prioritization_results.csv",
    mime="text/csv"
)
