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
    """Display race distance as a running distance, not a time."""
    if pd.isna(m):
        return "—"
    m = float(m)
    if abs(m - 5000) < 75:
        return "5K"
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


def athlete_best(df):
    x = df.dropna(subset=["time_sec"]).copy()
    if x.empty:
        return x
    return (
        x.sort_values("time_sec")
        .groupby(["gender", "athlete", "team", "distance_m"], as_index=False)
        .first()
    )


def projected_team(df, team_name, gender, distance_m, n=7):
    x = df[
        (df["team"].astype(str) == team_name)
        & (df["gender"].astype(str).str.lower() == gender.lower())
        & (df["distance_m"].sub(distance_m).abs().lt(75))
    ].dropna(subset=["time_sec"]).copy()

    if x.empty:
        return x

    # Best mark per athlete at this distance.
    x = (
        x.sort_values("time_sec")
        .groupby(["athlete", "team"], as_index=False)
        .first()
        .sort_values("time_sec")
        .head(n)
        .reset_index(drop=True)
    )
    x["runner_number"] = range(1, len(x) + 1)
    x["xc_points"] = x["runner_number"].apply(
        lambda r: r if r <= 5 else np.nan
    )
    return x


def score_from_times(times):
    if len(times) < 5:
        return np.nan
    return float(sum(sorted(times)[:5]))


def fmt_gap(v):
    if pd.isna(v):
        return "—"
    v = float(v)
    return f"+{v:.1f}s"


@st.cache_data(ttl=300)
def load_results():
    if not RESULTS.exists():
        return pd.DataFrame()

    df = pd.read_csv(RESULTS, low_memory=False)
    if df.empty:
        return df

    for c in ["date", "time_sec", "place", "grade", "distance_m", "points"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Remove obvious PDF column-merges/corrupt records.
    bad_team = df["team"].astype(str).str.contains(
        r"\)\s+\d+\s+[A-Z][A-Za-z'-]+", regex=True, na=False
    )
    bad_athlete = df["athlete"].astype(str).str.contains(
        r"\s+\d{1,2}\s+[A-Z][A-Za-z'-]+\s+\d{1,2}\s+",
        regex=True,
        na=False,
    )

    df = df[~bad_team & ~bad_athlete].copy()

    # Normalize common wrapped team names created by PDF extraction.
    replacements = {
        "La Quinta (La": "La Quinta (La Quinta)",
        "Canyon (Canyon": "Canyon (Canyon Country)",
    }
    df["team"] = df["team"].astype(str).replace(replacements)

    # Keep only plausible race results.
    df = df[
        df["athlete"].notna()
        & df["team"].notna()
        & df["time_sec"].between(180, 7200, inclusive="both")
        & df["grade"].between(1, 12, inclusive="both")
    ].copy()

    # Exact duplicate protection.
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
    if not x.empty:
        x["date"] = pd.to_datetime(x["date"], errors="coerce")
    return x


df = load_results()
meets = load_meets()

st.title("🏃 California XC 2026")
st.caption("Automated California high-school cross-country analytics • West Torrance focused")

if df.empty:
    st.error("No race results are currently available.")
    st.stop()

# Sidebar filters
st.sidebar.header("Filters")

genders = ["All"] + sorted(df["gender"].dropna().astype(str).unique().tolist())
gender = st.sidebar.selectbox("Gender", genders)

distance_values = sorted(df["distance_m"].dropna().unique().tolist())
distance_labels = {"All": None}
for d in distance_values:
    distance_labels[fmt_distance(d)] = d
distance_choice = st.sidebar.selectbox("Distance", ["All"] + [fmt_distance(d) for d in distance_values])

teams = ["All"] + sorted(df["team"].dropna().astype(str).unique().tolist())
team_choice = st.sidebar.selectbox("Team", teams)

f = df.copy()
if gender != "All":
    f = f[f["gender"].astype(str) == gender]
if distance_choice != "All":
    f = f[f["distance_m"] == distance_labels[distance_choice]]
if team_choice != "All":
    f = f[f["team"].astype(str) == team_choice]

# KPI row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Results", f"{len(f):,}")
c2.metric("Athletes", f["athlete"].nunique())
c3.metric("Teams", f["team"].nunique())
c4.metric("Meets", f["meet"].nunique())

tabs = st.tabs([
    "🔥 Daily Top 20",
    "🏆 Season Bests",
    "🏫 Team Rankings",
    "🔵 West Torrance",
    "⚔️ Team Matchup",
    "🎯 Where Do We Stand?",
    "📅 Meets",
])

# Daily top 20
with tabs[0]:
    st.subheader("Daily fastest performances")

    dates = sorted(f["date"].dropna().dt.date.unique(), reverse=True)
    if dates:
        chosen = st.selectbox("Race date", dates, key="daily_date")
        day = f[f["date"].dt.date == chosen].dropna(subset=["time_sec"])

        for g in ["Boys", "Girls"]:
            x = day[day["gender"].astype(str).str.lower() == g.lower()]
            x = x.sort_values("time_sec").head(20).copy()

            if not x.empty:
                x.insert(0, "Rank", range(1, len(x) + 1))
                x["Time"] = x["time_sec"].map(fmt)
                st.markdown(f"### {g}")
                st.dataframe(
                    x[["Rank", "athlete", "team", "Time", "meet", "race"]],
                    hide_index=True,
                    use_container_width=True,
                )

# Season bests
with tabs[1]:
    st.subheader("🏆 2026 Season Bests")
    st.caption("Fastest individual performances for the selected race distance.")

    season_distances = sorted(f["distance_m"].dropna().unique().tolist())

    if not season_distances:
        st.warning("No race-distance data is available.")
    else:
        dcol, gcol, tcol = st.columns(3)

        with dcol:
            season_distance_label = st.selectbox(
                "Race distance",
                [fmt_distance(d) for d in season_distances],
                key="season_best_distance",
            )
            season_distance = next(
                d for d in season_distances
                if fmt_distance(d) == season_distance_label
            )

        with gcol:
            season_gender = st.selectbox(
                "Gender",
                ["Boys", "Girls", "All"],
                key="season_best_gender",
            )

        with tcol:
            season_team = st.selectbox(
                "Team",
                ["All"] + sorted(
                    f["team"].dropna().astype(str).unique().tolist()
                ),
                key="season_best_team",
            )

        x = f[
            f["distance_m"].sub(season_distance).abs().lt(75)
        ].dropna(subset=["time_sec"]).copy()

        if season_gender != "All":
            x = x[
                x["gender"].astype(str).str.lower()
                == season_gender.lower()
            ]

        if season_team != "All":
            x = x[x["team"].astype(str) == season_team]

        # One season-best mark per athlete at the selected distance.
        x = x.sort_values("time_sec")
        x = x.groupby(
            ["gender", "athlete", "team"],
            as_index=False,
        ).first()

        x["Season Best"] = x["time_sec"].map(fmt)
        x["Distance"] = season_distance_label
        x = x.sort_values("time_sec").reset_index(drop=True)
        x.insert(0, "Rank", range(1, len(x) + 1))

        st.metric(
            f"{season_distance_label} Season-Best Performances",
            f"{len(x):,}",
        )

        st.dataframe(
            x[
                [
                    "Rank",
                    "gender",
                    "athlete",
                    "team",
                    "Distance",
                    "Season Best",
                    "meet",
                    "date",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )

# Team rankings
with tabs[2]:
    st.subheader("Team depth rankings")
    st.caption("Rank teams using their season-best runners at a specific race distance.")

    # Team Rankings gets its own distance selector so you can compare
    # 2 Mile, 4.8K, 5K, etc. independently of the other dashboard tabs.
    team_distances = sorted(f["distance_m"].dropna().unique().tolist())

    if not team_distances:
        st.warning("No race-distance data is available.")
    else:
        dcol, gcol, rcol = st.columns(3)

        with dcol:
            team_distance_label = st.selectbox(
                "Race distance",
                [fmt_distance(d) for d in team_distances],
                key="team_ranking_distance",
            )
            team_distance = next(
                d for d in team_distances
                if fmt_distance(d) == team_distance_label
            )

        with gcol:
            team_gender = st.selectbox(
                "Gender",
                ["Boys", "Girls", "All"],
                key="team_ranking_gender",
            )

        with rcol:
            metric = st.selectbox(
                "Rank teams by",
                ["5 Avg", "7 Avg", "10 Avg"],
                key="team_ranking_metric",
            )

        x = f[
            f["distance_m"].sub(team_distance).abs().lt(75)
        ].dropna(subset=["time_sec"]).sort_values("time_sec")

        if team_gender != "All":
            x = x[x["gender"].astype(str).str.lower() == team_gender.lower()]

        # One season-best performance per athlete for this distance.
        best = x.groupby(
            ["gender", "athlete", "team"],
            as_index=False,
        ).first()

        rows = []
        for (g, t), z in best.groupby(["gender", "team"]):
            vals = np.sort(z["time_sec"].to_numpy())
            rows.append({
                "Gender": g,
                "Team": t,
                "Distance": team_distance_label,
                "Runners": len(vals),
                "5 Avg": np.mean(vals[:5]) if len(vals) >= 5 else np.nan,
                "7 Avg": np.mean(vals[:7]) if len(vals) >= 7 else np.nan,
                "10 Avg": np.mean(vals[:10]) if len(vals) >= 10 else np.nan,
            })

        tr = pd.DataFrame(rows)

        if tr.empty:
            st.info(f"No team results found for {team_distance_label}.")
        else:
            tr = tr.sort_values(metric, na_position="last").copy()

            # Only rank teams that actually have enough runners for the
            # selected depth metric.
            required = {"5 Avg": 5, "7 Avg": 7, "10 Avg": 10}[metric]
            tr = tr[tr["Runners"] >= required].copy()
            tr.insert(0, "Rank", range(1, len(tr) + 1))

            for col in ["5 Avg", "7 Avg", "10 Avg"]:
                tr[col] = tr[col].map(fmt)

            st.dataframe(
                tr[
                    [
                        "Rank",
                        "Gender",
                        "Team",
                        "Distance",
                        "Runners",
                        "5 Avg",
                        "7 Avg",
                        "10 Avg",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )

# West Torrance
with tabs[3]:
    st.subheader("🔵 West Torrance Team Dashboard")

    wt = df[
        df["team"].astype(str).str.contains("West Torrance", case=False, na=False)
    ].copy()

    if wt.empty:
        st.warning("No West Torrance results found in the current database.")
    else:
        wt_distances = sorted(wt["distance_m"].dropna().unique().tolist())
        wcol1, wcol2 = st.columns(2)

        with wcol1:
            wt_gender = st.selectbox(
                "Gender",
                ["Boys", "Girls"],
                key="wt_gender",
            )
        with wcol2:
            wt_distance_label = st.selectbox(
                "Race distance",
                [fmt_distance(d) for d in wt_distances],
                key="wt_distance",
            )
            wt_distance = next(
                d for d in wt_distances
                if fmt_distance(d) == wt_distance_label
            )

        wt_filtered = wt[
            (wt["gender"].astype(str).str.lower() == wt_gender.lower())
            & (wt["distance_m"].sub(wt_distance).abs().lt(75))
        ].dropna(subset=["time_sec"]).copy()

        best = (
            wt_filtered.sort_values("time_sec")
            .groupby(["athlete", "team"], as_index=False)
            .first()
            .sort_values("time_sec")
            .reset_index(drop=True)
        )

        if best.empty:
            st.info("No West Torrance results for this distance/category.")
        else:
            best["Season Best"] = best["time_sec"].map(fmt)
            best["Gap to #1"] = (best["time_sec"] - best["time_sec"].iloc[0]).map(fmt_gap)
            best["Gap to Runner Ahead"] = (
                best["time_sec"].diff().map(fmt_gap)
            )
            best["Rank"] = range(1, len(best) + 1)

            vals = best["time_sec"].to_numpy()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Fastest", fmt(vals[0]))
            k2.metric("5-runner avg", fmt(np.mean(vals[:5])) if len(vals) >= 5 else "—")
            k3.metric("7-runner avg", fmt(np.mean(vals[:7])) if len(vals) >= 7 else "—")
            k4.metric("Depth to #7", fmt_gap(vals[6] - vals[0]) if len(vals) >= 7 else "—")

            st.markdown("### Team depth chart")
            depth = best[["Rank", "athlete", "grade", "Season Best", "Gap to #1", "Gap to Runner Ahead", "meet", "date"]].copy()
            st.dataframe(depth, hide_index=True, use_container_width=True)

            st.markdown("### Athlete progression")
            athlete = st.selectbox(
                "Select athlete",
                best["athlete"].tolist(),
                key="wt_athlete",
            )
            hist = wt_filtered[
                wt_filtered["athlete"].astype(str) == athlete
            ].sort_values("date").copy()

            if not hist.empty:
                hist["Display Time"] = hist["time_sec"].map(fmt)
                chart = hist.set_index("date")[["time_sec"]]
                st.line_chart(chart)
                first = hist["time_sec"].iloc[0]
                latest = hist["time_sec"].iloc[-1]
                sb = hist["time_sec"].min()
                c1, c2, c3 = st.columns(3)
                c1.metric("First race", fmt(first))
                c2.metric("Latest", fmt(latest), delta=f"{latest-first:+.1f}s")
                c3.metric("Season best", fmt(sb))

            st.markdown("### Projected XC lineup")
            st.caption("Uses season-best times as a baseline. Actual meet scoring can differ by course and race field.")

            lineup = best.head(7).copy()
            lineup["Projected Points"] = [1, 2, 3, 4, 5, "—", "—"][:len(lineup)]
            lineup["Time"] = lineup["time_sec"].map(fmt)
            lineup["Gap"] = (lineup["time_sec"] - lineup["time_sec"].iloc[0]).map(fmt_gap)
            st.dataframe(
                lineup[["Rank", "athlete", "grade", "Time", "Gap", "Projected Points"]],
                hide_index=True,
                use_container_width=True,
            )

            st.markdown("### Biggest season improvements")
            improvements = []
            for athlete_name, h in wt_filtered.groupby("athlete"):
                h = h.sort_values("date")
                if len(h) >= 2:
                    improvements.append({
                        "Athlete": athlete_name,
                        "First": h["time_sec"].iloc[0],
                        "Best": h["time_sec"].min(),
                        "Improvement": h["time_sec"].iloc[0] - h["time_sec"].min(),
                    })
            imp = pd.DataFrame(improvements)
            if not imp.empty:
                imp = imp.sort_values("Improvement", ascending=False)
                imp["First"] = imp["First"].map(fmt)
                imp["Best"] = imp["Best"].map(fmt)
                imp["Improvement"] = imp["Improvement"].map(lambda x: f"-{x:.1f}s")
                st.dataframe(imp, hide_index=True, use_container_width=True)

# Team matchup
with tabs[4]:
    st.subheader("⚔️ Team matchup")
    st.caption("Compare two teams using their fastest available runners at the selected distance.")

    all_teams = sorted(
        df["team"].dropna().astype(str).unique().tolist()
    )

    if len(all_teams) >= 2:
        left, right = st.columns(2)
        with left:
            team_a = st.selectbox("Team A", all_teams, index=all_teams.index("West Torrance") if "West Torrance" in all_teams else 0)
        with right:
            team_b = st.selectbox("Team B", all_teams, index=1)

        eligible = f.dropna(subset=["time_sec"]).copy()

        def team_depth(team_name):
            z = eligible[eligible["team"].astype(str) == team_name]
            z = z.sort_values("time_sec").groupby(
                ["gender", "athlete", "distance_m"],
                as_index=False,
            ).first()
            return z.sort_values("time_sec")

        a_df = team_depth(team_a)
        b_df = team_depth(team_b)

        g_choice = st.selectbox("Gender", ["Boys", "Girls"], key="match_gender")
        a_df = a_df[a_df["gender"].astype(str).str.lower() == g_choice.lower()]
        b_df = b_df[b_df["gender"].astype(str).str.lower() == g_choice.lower()]

        a_vals = a_df["time_sec"].to_numpy()
        b_vals = b_df["time_sec"].to_numpy()

        if len(a_vals) >= 5 and len(b_vals) >= 5:
            aa, bb, cc = st.columns(3)
            a5 = np.mean(a_vals[:5])
            b5 = np.mean(b_vals[:5])
            aa.metric(team_a, fmt(a5))
            bb.metric(team_b, fmt(b5))
            cc.metric(
                "Difference",
                fmt(abs(a5 - b5)),
                delta=f"{team_a} faster" if a5 < b5 else f"{team_b} faster",
                delta_color="normal",
            )

            comp = pd.DataFrame({
                "Runner": range(1, min(10, len(a_vals), len(b_vals)) + 1),
                team_a: [fmt(x) for x in a_vals[:10]],
                team_b: [fmt(x) for x in b_vals[:10]],
            })
            st.dataframe(comp, hide_index=True, use_container_width=True)
        else:
            st.info("Both teams need at least five runners in the selected category.")

# Where do we stand?
with tabs[5]:
    st.subheader("🎯 Where Do We Stand?")
    st.caption("Quick competitive snapshot using season-best depth at a selected distance.")

    all_teams = sorted(df["team"].dropna().astype(str).unique().tolist())
    distances = sorted(df["distance_m"].dropna().unique().tolist())

    if all_teams and distances:
        c1, c2, c3 = st.columns(3)
        with c1:
            wd_team = st.selectbox(
                "Team",
                all_teams,
                index=all_teams.index("West Torrance") if "West Torrance" in all_teams else 0,
                key="wd_team",
            )
        with c2:
            wd_gender = st.selectbox("Gender", ["Boys", "Girls"], key="wd_gender")
        with c3:
            wd_label = st.selectbox(
                "Distance",
                [fmt_distance(d) for d in distances],
                key="wd_distance",
            )
            wd_dist = next(d for d in distances if fmt_distance(d) == wd_label)

        rows = []
        for team in all_teams:
            z = projected_team(df, team, wd_gender, wd_dist, 7)
            if len(z) >= 5:
                score = score_from_times(z["time_sec"].tolist())
                rows.append({
                    "Team": team,
                    "Score": score,
                    "5 Avg": np.mean(z["time_sec"].head(5)),
                    "7 Depth": z["time_sec"].iloc[6] - z["time_sec"].iloc[0] if len(z) >= 7 else np.nan,
                    "Runners": len(z),
                })

        standings = pd.DataFrame(rows).sort_values("Score").reset_index(drop=True)
        if not standings.empty:
            standings["Rank"] = range(1, len(standings) + 1)
            me = standings[standings["Team"] == wd_team]
            if not me.empty:
                rank = int(me["Rank"].iloc[0])
                score = me["Score"].iloc[0]
                ahead = standings[standings["Rank"] == rank - 1]
                behind = standings[standings["Rank"] == rank + 1]

                a, b, c = st.columns(3)
                a.metric("Projected rank", f"#{rank}")
                b.metric("Projected score", f"{score:.0f}")
                if not ahead.empty:
                    b = behind
                    c.metric("Behind next team", f"{score - standings.loc[rank-2, 'Score']:.0f} pts")
                elif rank == 1:
                    c.metric("Standing", "Projected #1")
                else:
                    c.metric("Standing", "—")

            display = standings.copy()
            display["Score"] = display["Score"].map(lambda x: f"{x:.0f}")
            display["5 Avg"] = display["5 Avg"].map(fmt)
            display["7 Depth"] = display["7 Depth"].map(lambda x: fmt_gap(x))
            st.dataframe(
                display[["Rank", "Team", "Score", "5 Avg", "7 Depth", "Runners"]],
                hide_index=True,
                use_container_width=True,
            )


# Meets
with tabs[6]:
    st.subheader("2026 meet calendar")
    if not meets.empty:
        st.dataframe(
            meets.sort_values("date", ascending=False),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No meet metadata available.")

st.divider()
st.caption(
    "Data is automatically refreshed from the connected public/permitted results sources. "
    "Rows that fail basic integrity checks are excluded from analytics."
)
