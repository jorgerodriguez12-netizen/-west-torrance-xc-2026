import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path

st.set_page_config(page_title="West Torrance XC 2026", page_icon="🏃", layout="wide")
BASE=Path(__file__).parent
RESULTS=BASE/"data/results.csv"
MEETS=BASE/"data/meets.csv"

@st.cache_data(ttl=300)
def load_results():
    if not RESULTS.exists(): return pd.DataFrame()
    x=pd.read_csv(RESULTS)
    if x.empty:return x
    x["date"]=pd.to_datetime(x["date"],errors="coerce")
    x["time_sec"]=pd.to_numeric(x["time_sec"],errors="coerce")
    return x

@st.cache_data(ttl=300)
def load_meets():
    if not MEETS.exists(): return pd.DataFrame()
    x=pd.read_csv(MEETS)
    if not x.empty:x["date"]=pd.to_datetime(x["date"],errors="coerce")
    return x

def fmt(v):
    if pd.isna(v): return "—"
    v=float(v); return f"{int(v//60)}:{v%60:05.2f}"

df=load_results(); meets=load_meets()
st.title("🏃 West Torrance XC")
st.caption("2026 California High School Cross Country Analytics")

if df.empty:
    st.warning("The live database is ready, but no results have been imported yet.")
    st.write("The automatic importer checks the connected results providers and adds new completed races.")
else:
    st.sidebar.header("Filters")
    gender=st.sidebar.selectbox("Gender",["All"]+sorted(df.gender.dropna().astype(str).unique()))
    team=st.sidebar.selectbox("Team",["All"]+sorted(df.team.dropna().astype(str).unique()))
    dist=st.sidebar.selectbox("Distance",["All"]+sorted(df.distance_m.dropna().astype(str).unique()))
    f=df.copy()
    if gender!="All": f=f[f.gender.astype(str)==gender]
    if team!="All": f=f[f.team.astype(str)==team]
    if dist!="All": f=f[f.distance_m.astype(str)==dist]
    a,b,c,d=st.columns(4)
    a.metric("Results",f"{len(f):,}"); b.metric("Athletes",f"{f.athlete.nunique():,}")
    c.metric("Teams",f"{f.team.nunique():,}"); d.metric("Meets",f"{f.meet.nunique():,}")
    t1,t2,t3,t4,t5=st.tabs(["🔥 Today","🏆 Season","🏫 Teams","🔵 West Torrance","📅 Meets"])

    with t1:
        st.subheader("Top 20 performances by race day")
        dates=sorted(f.date.dropna().dt.date.unique(),reverse=True)
        if dates:
            chosen=st.selectbox("Race date",dates)
            day=f[f.date.dt.date==chosen].dropna(subset=["time_sec"])
            for g in ["Boys","Girls"]:
                x=day[day.gender.str.lower()==g.lower()].sort_values("time_sec").head(20).copy()
                if not x.empty:
                    x.insert(0,"Rank",range(1,len(x)+1)); x["Time"]=x.time_sec.map(fmt)
                    st.markdown(f"**{g} — Top 20**")
                    st.dataframe(x[["Rank","athlete","team","Time","meet","race"]],hide_index=True,use_container_width=True)

    with t2:
        st.subheader("2026 Season Bests")
        x=f.dropna(subset=["time_sec"]).sort_values("time_sec")
        # one best mark per athlete for each distance/gender
        x=x.groupby(["gender","athlete","team","distance_m"],as_index=False).first()
        x["Season Best"]=x.time_sec.map(fmt); x.insert(0,"Rank",range(1,len(x)+1))
        st.dataframe(x[["Rank","gender","athlete","team","distance_m","Season Best","meet","date"]],
                     hide_index=True,use_container_width=True)

    with t3:
        st.subheader("Team depth")
        st.caption("Season-best depth; same-meet scoring is retained in the race-level data.")
        x=f.dropna(subset=["time_sec"]).sort_values("time_sec")
        best=x.groupby(["gender","athlete","team","distance_m"],as_index=False).first()
        rows=[]
        for (g,t,distv),z in best.groupby(["gender","team","distance_m"]):
            v=np.sort(z.time_sec.values)
            rows.append({"Gender":g,"Team":t,"Distance":distv,"Runners":len(v),
                         "5 Avg":np.mean(v[:5]) if len(v)>=5 else np.nan,
                         "7 Avg":np.mean(v[:7]) if len(v)>=7 else np.nan,
                         "10 Avg":np.mean(v[:10]) if len(v)>=10 else np.nan})
        tr=pd.DataFrame(rows)
        for col in ["5 Avg","7 Avg","10 Avg"]: tr[col]=tr[col].map(fmt)
        st.dataframe(tr.sort_values(["Gender","5 Avg"]),hide_index=True,use_container_width=True)

    with t4:
        st.subheader("West Torrance — 2026")
        wt=df[df.team.astype(str).str.contains("West Torrance",case=False,na=False)].dropna(subset=["time_sec"])
        if wt.empty: st.info("No West Torrance results are connected yet.")
        else:
            best=wt.sort_values("time_sec").groupby(["gender","athlete","distance_m"],as_index=False).first()
            best["Season Best"]=best.time_sec.map(fmt)
            st.dataframe(best[["gender","athlete","grade","distance_m","Season Best","meet","date"]],
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
st.caption("Automatic results ingestion is limited to public/permitted result sources.")
