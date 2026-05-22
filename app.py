"""Clash of Clans Upgrade Optimizer — Streamlit web UI.

Usage:
    streamlit run app.py

Upload a Supercell player-stats dump (or use the bundled sample), pick a target TH
and builder count, and get an ordered upgrade plan that prioritizes high-value
upgrades (heroes, key defenses, troops) first.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.data.player import PlayerState
try:
    from src.data.player import parse_player_state_from_text
except ImportError:
    # Back-compat shim: an older player.py only exposes the path-based parser.
    import tempfile, os
    from src.data.player import parse_player_state as _parse_from_path

    def parse_player_state_from_text(raw: str, json_repo_path: Path) -> PlayerState:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(raw)
            tmp = f.name
        try:
            return _parse_from_path(Path(tmp), json_repo_path)
        finally:
            os.unlink(tmp)
from src.data.player_loader import jobs_from_player_state
from src.data.loaders import add_town_hall_gate
from src.data.schema import Track
from src.optim.lpt import lpt_schedule
from src.optim.cpsat import cpsat_schedule
from src.optim.resources import ResourceBudget
from src.optim.verify import verify_schedule
from src.optim.strength import upgrade_weight
from src.viz.schedule_list import to_dataframe, to_markdown


SAMPLE_STATS_PATH = ROOT / "sample_player.txt"
JSON_PATH = ROOT / "data" / "troops.json"
XLSX_PATH = ROOT / "data" / "buildings.xlsx"


st.set_page_config(page_title="CoC Upgrade Optimizer", layout="wide")
st.title("Clash of Clans — Upgrade Optimizer")
st.caption(
    "Get an ordered upgrade plan that prioritizes high-value progress: heroes and "
    "key defenses first, fillers later. Built on OR-Tools CP-SAT, scheduling 6 "
    "builders + Laboratory + Pet House in parallel."
)


# ---------- Sidebar inputs ----------
with st.sidebar:
    st.header("1. Player state")
    st.caption(
        "In Clash of Clans → Settings → More Settings → Copy ID, then paste your full "
        "player data below. Or upload a saved `.txt`."
    )
    input_mode = st.radio("Input method", ["Paste", "Upload file", "Use sample"], horizontal=True,
                          label_visibility="collapsed")

    raw_text = ""
    if input_mode == "Paste":
        raw_text = st.text_area(
            "Paste player JSON",
            height=180,
            placeholder='{"tag":"#XXX","timestamp":...,"heroes":[...],"units":[...],...}',
            help="The full JSON your in-game share copies to clipboard.",
        )
    elif input_mode == "Upload file":
        uploaded = st.file_uploader("Choose file", type=["txt", "json"], label_visibility="collapsed")
        if uploaded is not None:
            raw_text = uploaded.getvalue().decode("utf-8", errors="replace")
    else:
        raw_text = SAMPLE_STATS_PATH.read_text(encoding="utf-8", errors="replace")
        st.caption("Loaded bundled sample (rushed TH17/18 player).")

    if not raw_text.strip():
        st.info("Paste your player data above, upload a file, or pick the sample to continue.")
        st.stop()

    try:
        state: PlayerState = parse_player_state_from_text(raw_text, JSON_PATH)
    except Exception as e:
        st.error(f"Couldn't parse player data: {e}")
        st.stop()

    inferred_th = state.th_level or 15
    st.success(f"Parsed. Inferred TH **{inferred_th}**")
    th_override = st.number_input(
        "Current TH (override if wrong)",
        min_value=1, max_value=18, value=inferred_th,
    )

    st.header("2. Target & builders")
    target_th = st.number_input(
        "Target Town Hall", min_value=2, max_value=18,
        value=min(int(th_override) + 1, 18),
    )
    builders = st.slider("Builders", 1, 6, 6)

    st.header("3. Income (optional)")
    use_resources = st.checkbox("Constrain by income", value=False)
    if use_resources:
        rate_active = st.number_input(
            "Gold+Elixir per active hour", value=4_000_000,
            min_value=100_000, max_value=20_000_000, step=500_000,
        )
        hours_per_day = st.slider("Hours played per day", 0.5, 24.0, 6.0, 0.5)
        de_factor_pct = st.slider("DE rate (% of gold rate)", 0.1, 2.0, 0.5, 0.1)
        st.caption(
            f"Effective per-hour avg: gold/elixir = {int(rate_active * hours_per_day / 24):,}, "
            f"DE = {int(rate_active * de_factor_pct/100 * hours_per_day / 24):,}"
        )

    st.header("4. Settings")
    objective = st.radio(
        "Optimization objective",
        ["weighted_completion_time", "makespan"],
        format_func=lambda x: "Strength-first (recommended)" if x == "weighted_completion_time" else "Minimum total time",
        help="Strength-first puts high-value upgrades (heroes, key defenses, troops) earlier. "
             "Minimum total time minimizes the date when EVERYTHING is done.",
    )
    time_limit = st.slider("Solver time limit (s)", 5, 120, 30)
    use_player_buildings = st.checkbox(
        "Use player's actual building levels", value=False,
        help="Off = assume buildings at current-TH max (recommended; building ID mapping is best-effort).",
    )

    run = st.button("Compute upgrade plan", type="primary", use_container_width=True)


# ---------- Main column: player snapshot ----------
top_l, top_r = st.columns([1, 1])
with top_l:
    st.subheader("Player snapshot")
    st.write(state.summary())
    with st.expander("Heroes"):
        st.write({h: f"L{l}" for h, l in state.heroes.items()})
    with st.expander(f"Troops ({len(state.troops)})"):
        st.write({t: f"L{l}" for t, l in state.troops.items()})
    with st.expander(f"Spells ({len(state.spells)})"):
        st.write({s: f"L{l}" for s, l in state.spells.items()})
    with st.expander(f"Pets ({len(state.pets)})"):
        st.write({p: f"L{l}" for p, l in state.pets.items()})
    if state.upgrades_in_progress:
        with st.expander("Upgrades in progress at snapshot"):
            st.write(state.upgrades_in_progress)

if not run:
    with top_r:
        st.info(
            "Pick a target TH and click **Compute upgrade plan**.\n\n"
            "The optimizer will:\n"
            "1. Generate per-level upgrade jobs from your current state to target-TH max (walls excluded — handle those yourself)\n"
            "2. Schedule across builders + Lab + Pet House\n"
            "3. Prioritize high-strength-value upgrades first (heroes, key defenses, troops > storages, resource buildings)\n"
        )
    st.stop()


# ---------- Build job list ----------
with st.spinner("Building job list..."):
    jobs = jobs_from_player_state(
        state, target_th=int(target_th),
        json_path=JSON_PATH, xlsx_path=XLSX_PATH,
        use_player_buildings=bool(use_player_buildings),
        include_walls=False,
    )
    jobs = add_town_hall_gate(jobs, target_th=int(target_th))

if not jobs:
    st.warning("No upgrades needed — you're already at target-TH max.")
    st.stop()

with top_r:
    st.subheader("Work to do")
    by_track = {}
    for t in (Track.BUILDER, Track.LAB, Track.PET_HOUSE):
        by_track[t.value] = {
            "jobs": sum(1 for j in jobs if j.track == t),
            "work_days": round(sum(j.duration_sec for j in jobs if j.track == t) / 86400, 1),
        }
    st.dataframe(pd.DataFrame(by_track).T, use_container_width=True)


# ---------- LPT baseline + CP-SAT ----------
with st.spinner("Running greedy baseline..."):
    lpt = lpt_schedule(jobs, builders=int(builders))
    verify_schedule(lpt, jobs, builders=int(builders))

budget = None
if use_resources:
    budget = ResourceBudget(
        initial={"gold": 0, "elixir": 0, "dark_elixir": 0},
        rate_per_hour_active={
            "gold": int(rate_active),
            "elixir": int(rate_active),
            "dark_elixir": int(rate_active * de_factor_pct / 100),
        },
        active_hours_per_day=float(hours_per_day),
    )

with st.spinner(f"Optimizing (up to {time_limit}s)..."):
    t0 = time.time()
    try:
        cps = cpsat_schedule(
            jobs, builders=int(builders), time_limit_sec=float(time_limit),
            lpt_upper_bound=lpt.makespan_sec, resource_budget=budget,
            objective=objective,
        )
        verify_schedule(cps.schedule, jobs, builders=int(builders))
    except Exception as e:
        st.error(f"Solver failed: {e}")
        st.stop()
    solve_seconds = time.time() - t0


# ---------- Results header ----------
st.divider()
st.subheader("Plan")

# Build the per-row dataframe ONCE — used for all downstream views
sched_df = to_dataframe(cps.schedule)

# Headline metrics
total_weight = sum(upgrade_weight(j) for j in jobs)
done_in_first_quarter = sched_df[sched_df["end_day"] <= cps.schedule.makespan_days * 0.25]
weight_first_quarter = 0
weight_by_id = {j.id: upgrade_weight(j) for j in jobs}
job_by_id = {j.id: j for j in jobs}
for _, row in done_in_first_quarter.iterrows():
    # find job ID via name+from_level+to_level matching (sched_df doesn't store JobID directly here)
    # We use to_dataframe which uses chronological() — drop machine matching, use sched item
    pass

# Simpler: re-iterate schedule items
strength_quarter = sum(
    upgrade_weight(it.job)
    for it in cps.schedule.items
    if it.end_sec <= cps.schedule.makespan_sec * 0.25
)
strength_half = sum(
    upgrade_weight(it.job)
    for it in cps.schedule.items
    if it.end_sec <= cps.schedule.makespan_sec * 0.5
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Time to finish all", f"{cps.schedule.makespan_days:.0f} days",
          help=f"= {cps.schedule.makespan_days/365.25:.2f} years. {cps.solve_status} after {solve_seconds:.0f}s.")
m2.metric("Strength after 25%", f"{100*strength_quarter/total_weight:.0f}%",
          help=f"Fraction of total strength value gained by day {cps.schedule.makespan_days*0.25:.0f}.")
m3.metric("Strength after 50%", f"{100*strength_half/total_weight:.0f}%",
          help=f"Fraction of total strength value gained by day {cps.schedule.makespan_days*0.5:.0f}.")
# Bottleneck
builder_work = sum(j.duration_sec for j in jobs if j.track == Track.BUILDER) / 86400 / int(builders)
lab_work = sum(j.duration_sec for j in jobs if j.track == Track.LAB) / 86400
pet_work = sum(j.duration_sec for j in jobs if j.track == Track.PET_HOUSE) / 86400
bottleneck_name = max(
    [("builders", builder_work), ("lab", lab_work), ("pets", pet_work)],
    key=lambda x: x[1],
)[0]
m4.metric("Bottleneck", bottleneck_name,
          help=f"builders/m={builder_work:.0f}d, lab={lab_work:.0f}d, pets={pet_work:.0f}d")


# ---------- Ordered upgrade list — the headline view ----------
st.subheader("Upgrades in order — do these first to last")
show_n = st.slider("How many upgrades to show", 10, len(sched_df), min(50, len(sched_df)))
ordered = sched_df.head(show_n).copy()
ordered.index = ordered.index + 1
st.dataframe(ordered, use_container_width=True, height=600)


# ---------- Separated tabs: Lab | Pet House | Builders ----------
st.subheader("Full plan by machine")
lab_df = sched_df[sched_df["machine"] == "Laboratory"].drop(columns=["machine"]).reset_index(drop=True)
pet_df = sched_df[sched_df["machine"] == "Pet House"].drop(columns=["machine"]).reset_index(drop=True)
builder_dfs = {}
for i in range(1, int(builders) + 1):
    label = f"Builder {i}"
    sub = sched_df[sched_df["machine"] == label].drop(columns=["machine"]).reset_index(drop=True)
    if not sub.empty:
        builder_dfs[label] = sub

tab_labels = []
tab_dfs = []
if not lab_df.empty:
    tab_labels.append(f"Laboratory ({len(lab_df)})")
    tab_dfs.append(lab_df)
if not pet_df.empty:
    tab_labels.append(f"Pet House ({len(pet_df)})")
    tab_dfs.append(pet_df)
for label, sub in builder_dfs.items():
    tab_labels.append(f"{label} ({len(sub)})")
    tab_dfs.append(sub)

tabs = st.tabs(tab_labels)
for tab, sub in zip(tabs, tab_dfs):
    with tab:
        sub.index = sub.index + 1
        st.dataframe(sub, use_container_width=True, height=420)


# ---------- Export ----------
st.subheader("Export plan")
md_text = to_markdown(cps.schedule)
csv_text = sched_df.to_csv(index=False)
c1, c2 = st.columns(2)
c1.download_button(
    "Download as Markdown",
    md_text, file_name=f"coc_plan_th{target_th}.md", mime="text/markdown",
    use_container_width=True,
)
c2.download_button(
    "Download as CSV",
    csv_text, file_name=f"coc_plan_th{target_th}.csv", mime="text/csv",
    use_container_width=True,
)


# ---------- Notes ----------
with st.expander("How this works"):
    st.markdown("""
**Optimization objective.** "Strength-first" (default) minimizes the weighted sum of
completion times. Each upgrade carries a strength weight: heroes 100, key defenses
(Eagle, Inferno, Scattershot, Monolith, Spell Tower) 70, troops 55, spells 45, pets 40,
standard defenses 25, army buildings 18, lab/pet house 15, town hall 10, storages and
resource buildings 3. So the optimizer puts high-weight upgrades early and pushes
low-weight buildings to the end — same total time, way more useful strength early.

**Why three tracks.** Builders, the Laboratory (single researcher), and the Pet House
all run independently. The Lab usually dominates the makespan at high TH — 100s of days
of troop/spell research on a single machine. More builders doesn't help once the lab
becomes the bottleneck (typically m ≥ 3 at TH13+).

**Walls excluded.** They build instantly, drain resources, and are typically managed
manually. Handle them on the side.

**Income constraint (optional).** Models cumulative consumption ≤ initial + rate·time
per resource. Storage caps not enforced (they cause math infeasibility when income
exceeds cap, and don't change long-horizon plans).
    """)
