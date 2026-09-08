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
    st.subheader("🔵 West Torrance")
    wt = df[
        df["team"].astype(str).str.contains(
            "West Torrance", case=False, na=False
        )
    ].dropna(subset=["time_sec"]).copy()

    if wt.empty:
        st.warning("No West Torrance results found in the current database.")
    else:
        best = wt.sort_values("time_sec").groupby(
            ["gender", "athlete", "distance_m"],
            as_index=False,
        ).first()
        best["Season Best"] = best["time_sec"].map(fmt)
        best["Distance"] = best["distance_m"].map(fmt_distance)

        for g in ["Boys", "Girls"]:
            z = best[best["gender"].astype(str).str.lower() == g.lower()].sort_values(
                "time_sec"
            ).copy()

            if z.empty:
                continue

            st.markdown(f"### {g}")

            vals = z["time_sec"].to_numpy()
            a, b, c, d = st.columns(4)
            a.metric("#1", fmt(vals[0]))
            b.metric("5-runner avg", fmt(np.mean(vals[:5])) if len(vals) >= 5 else "—")
            c.metric("7-runner avg", fmt(np.mean(vals[:7])) if len(vals) >= 7 else "—")
            d.metric("Runners", len(vals))

            z.insert(0, "Rank", range(1, len(z) + 1))
            st.dataframe(
                z[
                    [
                        "Rank",
                        "athlete",
                        "grade",
                        "Distance",
                        "Season Best",
                        "meet",
                        "date",
                    ]
                ],
                hide_index=True,
                use_container_width=True,
            )

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

# Meets
with tabs[5]:
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
