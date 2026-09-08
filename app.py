
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path

st.set_page_config(
    page_title="West Torrance XC 2026",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DATA = Path(__file__).parent / "data"
RESULTS = DATA / "results.csv"
MEETS = DATA / "meets.csv"

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 2rem;}
div[data-testid="stMetricValue"] {font-size: 1.45rem;}
@media (max-width: 640px) {
  .block-container {padding-left: .75rem; padding-right: .75rem;}
  h1 {font-size: 1.65rem !important;}
  h2 {font-size: 1.25rem !important;}
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_results():
    if not RESULTS.exists():
        return pd.DataFrame()
    df = pd.read_csv(RESULTS)
    if df.empty:
        return df
    df["time_sec"] = pd.to_numeric(df["time_sec"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df

@st.cache_data(ttl=300)
def load_meets():
    if not MEETS.exists():
        return pd.DataFrame()
    df = pd.read_csv(MEETS)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df

def fmt(sec):
    if pd.isna(sec): return "—"
    sec = float(sec)
    return f"{int(sec//60)}:{sec%60:05.2f}"

df = load_results()
meets = load_meets()

st.title("🏃 West Torrance XC")
st.caption("2026 California High School Cross Country Analytics")

if df.empty:
    st.warning("No race results have been connected yet.")
else:
    st.sidebar.header("Filters")
    genders = ["All"] + sorted(df["gender"].dropna().astype(str).unique().tolist())
    gender = st.sidebar.selectbox("Gender", genders)
    teams = ["All"] + sorted(df["team"].dropna().astype(str).unique().tolist())
    team = st.sidebar.selectbox("Team", teams)
    distances = ["All"] + sorted(df["distance_m"].dropna().astype(str).unique().tolist())
    dist = st.sidebar.selectbox("Distance", distances)

    f = df.copy()
    if gender != "All": f = f[f["gender"].astype(str) == gender]
    if team != "All": f = f[f["team"].astype(str) == team]
    if dist != "All": f = f[f["distance_m"].astype(str) == dist]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Results", f"{len(f):,}")
    c2.metric("Athletes", f"{f['athlete'].nunique():,}")
    c3.metric("Teams", f"{f['team'].nunique():,}")
    c4.metric("Meets", f"{f['meet'].nunique():,}")

    t1,t2,t3,t4,t5 = st.tabs(["🔥 Today", "🏆 Season", "🏫 Teams", "🔵 West Torrance", "📅 Meets"])

    with t1:
        st.subheader("Top 20 performances by race day")
        dates = sorted(f["date"].dropna().dt.date.unique(), reverse=True)
        if dates:
            chosen = st.selectbox("Race date", dates)
            day = f[f["date"].dt.date == chosen].dropna(subset=["time_sec"])
            for g in ["Boys","Girls"]:
                x = day[day["gender"].str.lower() == g.lower()].sort_values("time_sec").head(20).copy()
                if not x.empty:
                    x.insert(0, "Rank", range(1, len(x)+1))
                    x["Time"] = x["time_sec"].map(fmt)
                    st.markdown(f"**{g} — Top 20**")
                    st.dataframe(x[["Rank","athlete","team","Time","meet","race"]],
                                 hide_index=True, use_container_width=True)

    with t2:
        st.subheader("2026 Season Bests")
        x = f.dropna(subset=["time_sec"]).sort_values("time_sec").copy()
        x = x.groupby(["gender","athlete","team"], as_index=False).first()
        x["Season Best"] = x["time_sec"].map(fmt)
        x.insert(0,"Rank",range(1,len(x)+1))
        st.dataframe(x[["Rank","gender","athlete","team","Season Best","meet","date"]],
                     hide_index=True, use_container_width=True)

    with t3:
        st.subheader("Team depth")
        st.caption("Season-best depth. Same-meet scoring can be added once meet-level scoring is available.")
        x = f.dropna(subset=["time_sec"]).sort_values("time_sec")
        best = x.groupby(["gender","athlete","team"], as_index=False).first()
        rows=[]
        for (g,t), grp in best.groupby(["gender","team"]):
            vals=np.sort(grp.time_sec.values)
            rows.append({
                "Gender":g, "Team":t, "Runners":len(vals),
                "5 Avg":np.mean(vals[:5]) if len(vals)>=5 else np.nan,
                "7 Avg":np.mean(vals[:7]) if len(vals)>=7 else np.nan,
                "10 Avg":np.mean(vals[:10]) if len(vals)>=10 else np.nan
            })
        tr=pd.DataFrame(rows)
        for c in ["5 Avg","7 Avg","10 Avg"]: tr[c]=tr[c].map(fmt)
        st.dataframe(tr, hide_index=True, use_container_width=True)

    with t4:
        st.subheader("West Torrance — 2026")
        wt=f[f["team"].str.contains("West Torrance",case=False,na=False)].dropna(subset=["time_sec"]).copy()
        if wt.empty:
            st.info("No West Torrance results are currently connected.")
        else:
            best=wt.sort_values("time_sec").groupby(["gender","athlete"],as_index=False).first()
            best["Season Best"]=best.time_sec.map(fmt)
            st.dataframe(best[["gender","athlete","grade","Season Best","meet","date"]],
                         hide_index=True,use_container_width=True)
            for g in ["Boys","Girls"]:
                vals=np.sort(best[best.gender.str.lower()==g.lower()].time_sec.values)
                if len(vals):
                    a,b,c,d=st.columns(4)
                    a.metric(f"{g} #1",fmt(vals[0]))
                    b.metric(f"{g} 5-runner avg",fmt(np.mean(vals[:5])) if len(vals)>=5 else "—")
                    c.metric(f"{g} 7-runner avg",fmt(np.mean(vals[:7])) if len(vals)>=7 else "—")
                    d.metric(f"{g} depth",len(vals))

    with t5:
        st.subheader("2026 Meet Calendar")
        st.dataframe(meets.sort_values("date",ascending=False),hide_index=True,use_container_width=True)

st.divider()
st.caption("Prototype dashboard. The production version should connect only to a permitted/authorized results feed or exported results source.")
