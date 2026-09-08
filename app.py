import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="California XC 2026",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE = Path(__file__).parent
RESULTS = BASE / "data" / "results.csv"
MEETS = BASE / "data" / "meets.csv"


def fmt(v):
    if pd.isna(v):
        return "—"
    v = float(v)
    return f"{int(v // 60)}:{v % 60:05.2f}"


def fmt_distance(m):
    if pd.isna(m):
        return "—"
    m = float(m)
    if abs(m - 5000) < 75:
        return "5K"
    if abs(m - 4800) < 75:
        return "4.8K"
    if abs(m - 3000) < 75:
        return "3K"
    if abs(m - 3200) < 75:
        return "2 Mile"
    if abs(m - 1609.344) < 35:
        return "1 Mile"
    if abs(m - 8046.72) < 100:
        return "5 Mile"
    if m >= 1000:
        return f"{m / 1000:.1f}K"
    return f"{m:.0f}m"


def fmt_gap(v):
    if pd.isna(v):
        return "—"
    return f"+{float(v):.1f}s"


def safe_distance_values(df):
    return sorted(pd.to_numeric(df["distance_m"], errors="coerce").dropna().unique().tolist())


def select_distance(df, label, key):
    vals = safe_distance_values(df)
    if not vals:
        return None, None
    labels = [fmt_distance(x) for x in vals]
    choice = st.selectbox(label, labels, key=key)
    target = next(x for x in vals if fmt_distance(x) == choice)
    return target, choice


def best_by_athlete(df, distance=None, gender=None, team=None):
    x = df.dropna(subset=["time_sec"]).copy()
    if distance is not None:
        x = x[x["distance_m"].sub(distance).abs().lt(75)]
    if gender and gender != "All":
        x = x[x["gender"].astype(str).str.lower() == gender.lower()]
    if team and team != "All":
        x = x[x["team"].astype(str) == str(team)]
    if x.empty:
        return x
    return (
        x.sort_values("time_sec")
        .groupby(["gender", "athlete", "team"], as_index=False)
        .first()
        .sort_values("time_sec")
        .reset_index(drop=True)
    )


def team_lineup(df, team_name, gender, distance, n=7):
    x = best_by_athlete(df, distance, gender, team_name)
    return x.head(n).reset_index(drop=True)


def xc_score(lineup):
    if len(lineup) < 5:
        return np.nan
    # Standard high-school 5-runner scoring: places 1-5 sum.
    return float(sum(range(1, 6))) if False else float(sum(range(1, 6)))


def simulated_score_from_field(field, team_name, gender, distance, n=7):
    """Score a team's season-best lineup against all other teams in the same field."""
    team_data = {}
    for team in sorted(field["team"].dropna().astype(str).unique()):
        z = team_lineup(field, team, gender, distance, n)
        if len(z) >= 5:
            team_data[team] = z

    if team_name not in team_data:
        return None, team_data

    # Merge all teams' runners into one field and assign places by time.
    runners = []
    for team, z in team_data.items():
        zz = z.copy()
        zz["Team"] = team
        runners.append(zz)
    merged = pd.concat(runners, ignore_index=True).sort_values("time_sec").reset_index(drop=True)
    merged["place"] = np.arange(1, len(merged) + 1)

    # XC scoring: first 5 scoring runners, with displacement by non-scoring teammates.
    scores = {}
    for team, z in team_data.items():
        athlete_names = set(z.head(5)["athlete"].astype(str))
        scores[team] = float(merged[merged["Team"] == team]["place"].head(5).sum())
    return scores.get(team_name), scores


@st.cache_data(ttl=300)
def load_results():
    if not RESULTS.exists():
        return pd.DataFrame()
    df = pd.read_csv(RESULTS, low_memory=False)
    if df.empty:
        return df

    for c in ["time_sec", "place", "grade", "distance_m", "points"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")

    for c in ["athlete", "team", "gender", "meet", "race"]:
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("").astype(str).str.strip()

    # Exclude duplicate/administrative "Merge" races from analytics.
    # Meets such as Great Cow Run can contain both a Merge race and the
    # actual Varsity/Sophomore/etc. races. The Merge race is redundant,
    # so it should not appear in rankings, athlete histories, or profiles.
    df = df[~df["race"].str.contains(r"\bmerge\b", case=False, regex=True, na=False)].copy()

    # Remove obvious PDF column-merge/corrupt records.
    bad_team = df["team"].str.contains(r"\)\s+\d+\s+[A-Z][A-Za-z'-]+", regex=True, na=False)
    bad_athlete = df["athlete"].str.contains(r"\s+\d{1,2}\s+[A-Z][A-Za-z'-]+\s+\d{1,2}\s+", regex=True, na=False)
    df = df[~bad_team & ~bad_athlete].copy()

    # Plausible high-school race results.
    df = df[
        df["athlete"].ne("")
        & df["team"].ne("")
        & df["time_sec"].between(180, 7200, inclusive="both")
        & df["grade"].between(1, 12, inclusive="both")
    ].copy()

    df = df.drop_duplicates(
        subset=["date", "meet", "race", "athlete", "team", "time_sec"],
        keep="first",
    )
    return df


@st.cache_data(ttl=300)
def load_meets():
    if not MEETS.exists():
        return pd.DataFrame()
    x = pd.read_csv(MEETS)
    if not x.empty and "date" in x.columns:
        x["date"] = pd.to_datetime(x["date"], errors="coerce")
    return x


df = load_results()
meets = load_meets()

st.title("🏃 California XC 2026")
st.caption("Automated California high-school cross-country analytics • West Torrance focused")

if df.empty:
    st.error("No race results are currently available.")
    st.stop()

# Global filters
st.sidebar.header("Global Filters")
gender = st.sidebar.selectbox("Gender", ["All"] + sorted(df["gender"].unique().tolist()), key="global_gender")
distance_values = safe_distance_values(df)
distance_map = {fmt_distance(x): x for x in distance_values}
distance_choice = st.sidebar.selectbox("Distance", ["All"] + list(distance_map.keys()), key="global_distance")
team_choice = st.sidebar.selectbox("Team", ["All"] + sorted(df["team"].unique().tolist()), key="global_team")

f = df.copy()
if gender != "All":
    f = f[f["gender"].str.lower() == gender.lower()]
if distance_choice != "All":
    f = f[f["distance_m"].sub(distance_map[distance_choice]).abs().lt(75)]
if team_choice != "All":
    f = f[f["team"] == team_choice]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Results", f"{len(f):,}")
c2.metric("Athletes", f["athlete"].nunique())
c3.metric("Teams", f["team"].nunique())
c4.metric("Meets", f["meet"].nunique())

# Optional metadata fields are supported automatically if the importer adds them later.
metadata_fields = [c for c in ["league", "cif_section", "division", "course"] if c in df.columns]

TABS = [
    "🔥 Daily Top 20",
    "🇺🇸 California Rankings",
    "🏆 Season Bests",
    "🏫 Team Rankings",
    "🔵 West Torrance",
    "👤 Athlete Profiles",
    "⚔️ Team Matchup",
    "🧮 Lineup Simulator",
    "🎯 Where Do We Stand?",
    "📝 Meet Recap",
    "📈 Movers",
    "📅 Meets",
]
tabs = st.tabs(TABS)

# 1 Daily Top 20
with tabs[0]:
    st.subheader("🔥 Daily Top 20")
    dates = sorted(f["date"].dropna().dt.date.unique(), reverse=True)
    if not dates:
        st.info("No dated results available.")
    else:
        chosen = st.selectbox("Race date", dates, key="daily_date")
        day = f[f["date"].dt.date == chosen].dropna(subset=["time_sec"])
        dtarget, dlabel = select_distance(day, "Race distance", "daily_distance") if not day.empty else (None, None)
        if dtarget is not None:
            day = day[day["distance_m"].sub(dtarget).abs().lt(75)]
        for g in ["Boys", "Girls"]:
            x = day[day["gender"].str.lower() == g.lower()].sort_values("time_sec").head(20).copy()
            if not x.empty:
                x.insert(0, "Rank", range(1, len(x) + 1))
                x["Time"] = x["time_sec"].map(fmt)
                st.markdown(f"### {g} • {dlabel or 'All distances'}")
                st.dataframe(x[["Rank", "athlete", "team", "Time", "meet", "race"]], hide_index=True, use_container_width=True)

# 2 California Rankings
with tabs[1]:
    st.subheader("🇺🇸 California Rankings")
    st.caption("Statewide rankings from the results currently loaded in the database. Coverage expands as new timing sources are added.")
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        rank_distance, rank_distance_label = select_distance(df, "Distance", "ca_rank_distance")
    with rc2:
        rank_gender = st.selectbox("Gender", ["Boys", "Girls"], key="ca_rank_gender")
    with rc3:
        grade_choices = ["All"] + [str(x) for x in sorted(df["grade"].dropna().unique())]
        rank_grade = st.selectbox("Grade", grade_choices, key="ca_rank_grade")
    with rc4:
        rank_scope = st.selectbox("Ranking", ["Season", "Latest race day"], key="ca_rank_scope")

    rx = df[(df["gender"].str.lower() == rank_gender.lower()) & df["distance_m"].sub(rank_distance).abs().lt(75)].copy()
    if rank_grade != "All":
        rx = rx[rx["grade"] == float(rank_grade)]
    if rank_scope == "Latest race day" and not rx.empty:
        latest = rx["date"].max().date()
        rx = rx[rx["date"].dt.date == latest]
    rx = best_by_athlete(rx)
    rx.insert(0, "Rank", range(1, len(rx) + 1))
    rx["Time"] = rx["time_sec"].map(fmt)
    rx["Distance"] = rank_distance_label
    st.dataframe(rx.head(100)[["Rank", "athlete", "team", "grade", "Distance", "Time", "meet", "date"]], hide_index=True, use_container_width=True)

    if not metadata_fields:
        st.info("CIF section, division, and league filters are ready for the database once team metadata is added. I am not guessing those classifications from names.")

# 3 Season Bests
with tabs[2]:
    st.subheader("🏆 2026 Season Bests")
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        season_distance, season_distance_label = select_distance(f, "Race distance", "season_best_distance")
    with sc2:
        season_gender = st.selectbox("Gender", ["Boys", "Girls", "All"], key="season_best_gender")
    with sc3:
        season_team = st.selectbox("Team", ["All"] + sorted(f["team"].unique().tolist()), key="season_best_team")

    x = best_by_athlete(f, season_distance, season_gender, season_team)
    if x.empty:
        st.info("No season-best performances match those filters.")
    else:
        x["Season Best"] = x["time_sec"].map(fmt)
        x["Distance"] = season_distance_label
        x.insert(0, "Rank", range(1, len(x) + 1))
        st.dataframe(x[["Rank", "gender", "athlete", "team", "grade", "Distance", "Season Best", "meet", "date"]], hide_index=True, use_container_width=True)

# 4 Team Rankings
with tabs[3]:
    st.subheader("🏫 Team Depth Rankings")
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        team_distance, team_distance_label = select_distance(f, "Race distance", "team_ranking_distance")
    with tc2:
        team_gender = st.selectbox("Gender", ["Boys", "Girls"], key="team_ranking_gender")
    with tc3:
        metric = st.selectbox("Rank teams by", ["5 Avg", "7 Avg", "10 Avg"], key="team_ranking_metric")

    if team_distance is not None:
        x = f[f["distance_m"].sub(team_distance).abs().lt(75)].copy()
        x = x[x["gender"].str.lower() == team_gender.lower()]
        best = best_by_athlete(x)
        rows = []
        for team, z in best.groupby("team"):
            vals = np.sort(z["time_sec"].to_numpy())
            rows.append({
                "Team": team,
                "Distance": team_distance_label,
                "Runners": len(vals),
                "5 Avg": np.mean(vals[:5]) if len(vals) >= 5 else np.nan,
                "7 Avg": np.mean(vals[:7]) if len(vals) >= 7 else np.nan,
                "10 Avg": np.mean(vals[:10]) if len(vals) >= 10 else np.nan,
            })
        tr = pd.DataFrame(rows)
        if not tr.empty:
            required = {"5 Avg": 5, "7 Avg": 7, "10 Avg": 10}[metric]
            tr = tr[tr["Runners"] >= required].sort_values(metric).reset_index(drop=True)
            tr.insert(0, "Rank", range(1, len(tr) + 1))
            for col in ["5 Avg", "7 Avg", "10 Avg"]:
                tr[col] = tr[col].map(fmt)
            st.dataframe(tr[["Rank", "Team", "Distance", "Runners", "5 Avg", "7 Avg", "10 Avg"]], hide_index=True, use_container_width=True)
        else:
            st.info("No qualifying teams for this distance/category.")

# 5 West Torrance
with tabs[4]:
    st.subheader("🔵 West Torrance Team Dashboard")
    wt = df[df["team"].str.contains("West Torrance", case=False, na=False)].copy()
    if wt.empty:
        st.warning("No West Torrance results found in the current database.")
    else:
        wc1, wc2 = st.columns(2)
        with wc1:
            wt_gender = st.selectbox("Gender", ["Boys", "Girls"], key="wt_gender")
        with wc2:
            wt_distance, wt_distance_label = select_distance(wt, "Race distance", "wt_distance")
        wt_f = wt[(wt["gender"].str.lower() == wt_gender.lower()) & wt["distance_m"].sub(wt_distance).abs().lt(75)]
        best = best_by_athlete(wt_f)
        if best.empty:
            st.info("No West Torrance results for this category.")
        else:
            vals = best["time_sec"].to_numpy()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Fastest", fmt(vals[0]))
            k2.metric("5-runner avg", fmt(np.mean(vals[:5])) if len(vals) >= 5 else "—")
            k3.metric("7-runner avg", fmt(np.mean(vals[:7])) if len(vals) >= 7 else "—")
            k4.metric("Depth to #7", fmt_gap(vals[6] - vals[0]) if len(vals) >= 7 else "—")
            best["Rank"] = range(1, len(best) + 1)
            best["Season Best"] = best["time_sec"].map(fmt)
            best["Gap to #1"] = (best["time_sec"] - best["time_sec"].iloc[0]).map(fmt_gap)
            best["Gap to Runner Ahead"] = best["time_sec"].diff().map(fmt_gap)
            st.markdown("### Depth chart")
            st.dataframe(best[["Rank", "athlete", "grade", "Season Best", "Gap to #1", "Gap to Runner Ahead", "meet", "date"]], hide_index=True, use_container_width=True)

            st.markdown("### Projected lineup")
            lineup = best.head(7).copy()
            lineup["Projected Points"] = [1, 2, 3, 4, 5, "—", "—"][:len(lineup)]
            lineup["Time"] = lineup["time_sec"].map(fmt)
            lineup["Gap"] = (lineup["time_sec"] - lineup["time_sec"].iloc[0]).map(fmt_gap)
            st.dataframe(lineup[["Rank", "athlete", "grade", "Time", "Gap", "Projected Points"]], hide_index=True, use_container_width=True)

            st.markdown("### Athlete progression")
            athlete = st.selectbox("Select athlete", best["athlete"].tolist(), key="wt_athlete")
            hist = wt_f[wt_f["athlete"] == athlete].sort_values("date")
            if not hist.empty:
                st.line_chart(hist.set_index("date")["time_sec"])
                first, latest, sb = hist["time_sec"].iloc[0], hist["time_sec"].iloc[-1], hist["time_sec"].min()
                a, b, c = st.columns(3)
                a.metric("First race", fmt(first))
                b.metric("Latest", fmt(latest), delta=f"{latest-first:+.1f}s")
                c.metric("Season best", fmt(sb))

# 6 Athlete Profiles
with tabs[5]:
    st.subheader("👤 Athlete Profiles")

    athlete_names = sorted(df["athlete"].unique().tolist())

    # Search first, then choose from the much smaller filtered dropdown.
    # This is easier to use when the database contains thousands of athletes.
    athlete_search = st.text_input(
        "🔎 Search athlete",
        placeholder="Type an athlete's name...",
        key="athlete_search",
        type="search",
    )

    if athlete_search.strip():
        search_term = athlete_search.strip().lower()
        filtered_athletes = [
            name for name in athlete_names
            if search_term in name.lower()
        ]
    else:
        filtered_athletes = athlete_names

    if not filtered_athletes:
        st.warning("No athletes found. Try a different name.")
    else:
        selected_athlete = st.selectbox(
            f"Select athlete ({len(filtered_athletes)} matches)",
            filtered_athletes,
            key="profile_athlete",
        )
        ah = df[df["athlete"] == selected_athlete].sort_values("date").copy()
    if filtered_athletes and not ah.empty:
        info1, info2, info3, info4 = st.columns(4)
        info1.metric("Team", ah["team"].mode().iloc[0])
        info2.metric("Grade", str(int(ah["grade"].dropna().iloc[-1])) if ah["grade"].notna().any() else "—")
        info3.metric("Races", str(len(ah)))
        info4.metric("Overall best", fmt(ah["time_sec"].min()))
        st.markdown("### Race history")
        ah["Time"] = ah["time_sec"].map(fmt)
        ah["Distance"] = ah["distance_m"].map(fmt_distance)
        st.dataframe(ah[["date", "meet", "race", "Distance", "Time", "place"]], hide_index=True, use_container_width=True)
        st.markdown("### Progression")
        st.line_chart(ah.set_index("date")["time_sec"])

# 7 Team Matchup
with tabs[6]:
    st.subheader("⚔️ Head-to-Head Team Matchup")
    all_teams = sorted(df["team"].unique().tolist())
    if len(all_teams) >= 2:
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            team_a = st.selectbox("Team A", all_teams, index=all_teams.index("West Torrance") if "West Torrance" in all_teams else 0, key="match_a")
        with mc2:
            team_b = st.selectbox("Team B", all_teams, index=1 if len(all_teams) > 1 else 0, key="match_b")
        with mc3:
            match_gender = st.selectbox("Gender", ["Boys", "Girls"], key="match_gender")
        match_distance, match_distance_label = select_distance(df, "Distance", "match_distance")
        if team_a == team_b:
            st.warning("Choose two different teams.")
        else:
            field = df[(df["gender"].str.lower() == match_gender.lower()) & df["distance_m"].sub(match_distance).abs().lt(75)].copy()
            sa, scores = simulated_score_from_field(field, team_a, match_gender, match_distance, 7)
            sb = scores.get(team_b) if scores else None
            if sa is None or sb is None:
                st.info("Both teams need at least five valid runners for this matchup.")
            else:
                a, b, c = st.columns(3)
                a.metric(team_a, f"{sa:.0f} pts")
                b.metric(team_b, f"{sb:.0f} pts")
                if sa < sb:
                    c.metric("Projected winner", team_a, delta=f"{sb-sa:.0f} points")
                elif sb < sa:
                    c.metric("Projected winner", team_b, delta=f"{sa-sb:.0f} points")
                else:
                    c.metric("Projected result", "Tie")
                za = team_lineup(field, team_a, match_gender, match_distance, 7)
                zb = team_lineup(field, team_b, match_gender, match_distance, 7)
                n = min(7, len(za), len(zb))
                comp = pd.DataFrame({
                    "Runner": range(1, n + 1),
                    team_a: [fmt(x) for x in za["time_sec"].head(n)],
                    team_b: [fmt(x) for x in zb["time_sec"].head(n)],
                })
                st.dataframe(comp, hide_index=True, use_container_width=True)

# 8 Lineup Simulator
with tabs[7]:
    st.subheader("🧮 What-If Lineup Simulator")
    st.caption("Choose seven runners and see how their projected scoring position changes against the current database field.")
    sim_team = st.selectbox("Team", [x for x in all_teams if "West Torrance" in x] + [x for x in all_teams if "West Torrance" not in x], key="sim_team")
    sim_gender = st.selectbox("Gender", ["Boys", "Girls"], key="sim_gender")
    sim_distance, sim_distance_label = select_distance(df, "Distance", "sim_distance")
    sim_pool = best_by_athlete(df, sim_distance, sim_gender, sim_team)
    if len(sim_pool) < 5:
        st.info("This team has fewer than five runners at the selected distance.")
    else:
        names = sim_pool["athlete"].tolist()
        default = names[:min(7, len(names))]
        selected = st.multiselect("Select 5–7 runners", names, default=default, key="sim_selected")
        if len(selected) < 5:
            st.warning("Select at least five runners.")
        else:
            lineup = sim_pool[sim_pool["athlete"].isin(selected)].copy().sort_values("time_sec")
            # Compare the chosen lineup to every other team using the same race distance.
            field = df[(df["gender"].str.lower() == sim_gender.lower()) & df["distance_m"].sub(sim_distance).abs().lt(75)].copy()
            others = {}
            for team in sorted(field["team"].unique()):
                if team == sim_team:
                    continue
                z = team_lineup(field, team, sim_gender, sim_distance, 7)
                if len(z) >= 5:
                    others[team] = z
            runners = []
            mine = lineup.copy()
            mine["Team"] = sim_team
            runners.append(mine)
            for team, z in others.items():
                zz = z.copy(); zz["Team"] = team; runners.append(zz)
            merged = pd.concat(runners, ignore_index=True).sort_values("time_sec").reset_index(drop=True)
            merged["place"] = range(1, len(merged) + 1)
            myscore = merged[merged["Team"] == sim_team]["place"].head(5).sum()
            scores = merged.groupby("Team").apply(lambda z: z["place"].head(5).sum()).sort_values()
            rank = int(scores.reset_index(drop=True).tolist().index(myscore) + 1) if myscore in scores.values else None
            a, b, c = st.columns(3)
            a.metric("Projected score", f"{myscore:.0f}")
            b.metric("Projected rank", f"#{rank}" if rank else "—")
            c.metric("5-runner average", fmt(lineup["time_sec"].head(5).mean()))
            lineup["Time"] = lineup["time_sec"].map(fmt)
            st.dataframe(lineup[["athlete", "grade", "Time"]], hide_index=True, use_container_width=True)

# 9 Where do we stand
with tabs[8]:
    st.subheader("🎯 Where Do We Stand?")
    wd_team = st.selectbox("Team", all_teams, index=all_teams.index("West Torrance") if "West Torrance" in all_teams else 0, key="wd_team")
    wd_gender = st.selectbox("Gender", ["Boys", "Girls"], key="wd_gender")
    wd_distance, wd_distance_label = select_distance(df, "Distance", "wd_distance")
    field = df[(df["gender"].str.lower() == wd_gender.lower()) & df["distance_m"].sub(wd_distance).abs().lt(75)].copy()
    rows = []
    for team in sorted(field["team"].unique()):
        z = team_lineup(field, team, wd_gender, wd_distance, 7)
        if len(z) >= 5:
            rows.append({"Team": team, "Score Proxy": z["time_sec"].head(5).sum(), "5 Avg": z["time_sec"].head(5).mean(), "7 Depth": z["time_sec"].iloc[6] - z["time_sec"].iloc[0] if len(z) >= 7 else np.nan, "Runners": len(z)})
    standings = pd.DataFrame(rows)
    if standings.empty:
        st.info("No teams have five valid runners for this category.")
    else:
        # Time proxy ranks teams without pretending that raw time sum is official XC scoring.
        standings = standings.sort_values("Score Proxy").reset_index(drop=True)
        standings["Rank"] = range(1, len(standings) + 1)
        me = standings[standings["Team"] == wd_team]
        if not me.empty:
            rank = int(me["Rank"].iloc[0])
            a, b, c = st.columns(3)
            a.metric("Projected time rank", f"#{rank}")
            b.metric("5-runner average", fmt(me["5 Avg"].iloc[0]))
            if rank > 1:
                gap = me["Score Proxy"].iloc[0] - standings.loc[rank - 2, "Score Proxy"]
                c.metric("Gap to team ahead", fmt_gap(gap))
            else:
                c.metric("Standing", "Projected #1")
        display = standings.copy()
        display["5 Avg"] = display["5 Avg"].map(fmt)
        display["7 Depth"] = display["7 Depth"].map(fmt_gap)
        st.dataframe(display[["Rank", "Team", "5 Avg", "7 Depth", "Runners"]], hide_index=True, use_container_width=True)

# 10 Meet Recap
with tabs[9]:
    st.subheader("📝 Meet Recap")
    meet_names = sorted(df["meet"].unique().tolist(), reverse=True)
    recap_meet = st.selectbox("Meet", meet_names, key="recap_meet")
    rd = df[df["meet"] == recap_meet].copy()
    if rd.empty:
        st.info("No results for this meet.")
    else:
        recap_team = st.selectbox("Team", ["All"] + sorted(rd["team"].unique().tolist()), key="recap_team")
        if recap_team != "All":
            rd = rd[rd["team"] == recap_team]
        st.write(f"**Date:** {rd['date'].min().date() if rd['date'].notna().any() else '—'}")
        for g in ["Boys", "Girls"]:
            z = rd[rd["gender"].str.lower() == g.lower()].sort_values("time_sec").head(7).copy()
            if not z.empty:
                z["Time"] = z["time_sec"].map(fmt)
                st.markdown(f"### {g}")
                st.dataframe(z[["athlete", "grade", "team", "Time", "place"]], hide_index=True, use_container_width=True)
        if recap_team != "All":
            st.markdown("### Race takeaways")
            season_pool = df[df["team"] == recap_team]
            for g in ["Boys", "Girls"]:
                z = rd[rd["gender"].str.lower() == g.lower()]
                if z.empty:
                    continue
                takeaways = []
                for _, r in z.iterrows():
                    same = season_pool[(season_pool["athlete"] == r["athlete"]) & (season_pool["distance_m"].sub(r["distance_m"]).abs().lt(75))]
                    if not same.empty:
                        prev_best = same["time_sec"].min()
                        takeaways.append({"Athlete": r["athlete"], "Race": r["time_sec"], "Previous/season best": prev_best, "Delta": r["time_sec"] - prev_best})
                td = pd.DataFrame(takeaways)
                if not td.empty:
                    td["Race"] = td["Race"].map(fmt)
                    td["Previous/season best"] = td["Previous/season best"].map(fmt)
                    td["Delta"] = td["Delta"].map(lambda x: f"{x:+.1f}s")
                    st.dataframe(td, hide_index=True, use_container_width=True)

# 11 Movers
with tabs[10]:
    st.subheader("📈 Biggest Movers")
    st.caption("Improvement from an athlete's first loaded race to their best loaded performance at the same distance.")
    mc1, mc2 = st.columns(2)
    with mc1:
        mover_gender = st.selectbox("Gender", ["Boys", "Girls"], key="mover_gender")
    with mc2:
        mover_distance, mover_distance_label = select_distance(df, "Distance", "mover_distance")
    mf = df[(df["gender"].str.lower() == mover_gender.lower()) & df["distance_m"].sub(mover_distance).abs().lt(75)].copy()
    movers = []
    for athlete, z in mf.groupby("athlete"):
        z = z.sort_values("date")
        if len(z) >= 2:
            first = z["time_sec"].iloc[0]
            best = z["time_sec"].min()
            movers.append({"Athlete": athlete, "Team": z["team"].iloc[-1], "First": first, "Best": best, "Improvement": first - best, "Races": len(z)})
    mv = pd.DataFrame(movers).sort_values("Improvement", ascending=False) if movers else pd.DataFrame()
    if mv.empty:
        st.info("Not enough repeat races to calculate movers.")
    else:
        mv["First"] = mv["First"].map(fmt); mv["Best"] = mv["Best"].map(fmt); mv["Improvement"] = mv["Improvement"].map(lambda x: f"-{x:.1f}s")
        st.dataframe(mv.head(50), hide_index=True, use_container_width=True)

# 12 Meets
with tabs[11]:
    st.subheader("📅 2026 Meet Calendar")
    if not meets.empty:
        st.dataframe(meets.sort_values("date", ascending=False), hide_index=True, use_container_width=True)
    else:
        st.info("No meet metadata available.")

st.divider()
st.caption("Analytics are limited to the results currently loaded. CIF/league/division fields will be surfaced when reliable team metadata is added; the app does not guess classifications.")
