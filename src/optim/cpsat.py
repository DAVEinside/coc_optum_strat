"""CP-SAT optimal scheduler (Google OR-Tools).

Models:
- Each job as an IntervalVar(start, duration_fixed, end)
- Builder track: AddCumulative(builder_intervals, capacity=m)
- Lab track: AddNoOverlap(lab_intervals)
- Pet House track: AddNoOverlap(pet_intervals)
- Free track (walls): no machine constraint; just precedence
- Precedence: end(parent) <= start(child) for every edge

Objective: minimize makespan = max(end_i)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from src.data.schema import Track, UpgradeJob
from src.optim.lpt import Schedule, ScheduledJob, lpt_schedule
from src.optim.resources import ResourceBudget, add_resource_constraints
from src.optim.strength import upgrade_weight


@dataclass
class CPSATResult:
    schedule: Schedule
    solve_status: str
    solve_wall_seconds: float
    best_objective: int


def cpsat_schedule(
    jobs: List[UpgradeJob],
    builders: int,
    time_limit_sec: float = 60.0,
    horizon_buffer_pct: float = 1.5,
    lpt_upper_bound: Optional[int] = None,
    resource_budget: Optional[ResourceBudget] = None,
    objective: str = "weighted_completion_time",
    fallback_to_lpt: bool = True,
) -> CPSATResult:
    """Solve to optimality (or best-found within time_limit_sec) and return a Schedule.

    `objective`:
      - "weighted_completion_time" (default): minimize sum(weight_j * end_j). Pushes
        high-strength-value upgrades (heroes, key defenses, troops) earlier so the
        player gains strength fastest. All jobs still complete.
      - "makespan": classic min total time to finish all jobs.

    If `lpt_upper_bound` is provided, tightens the horizon and speeds up solving.
    If `resource_budget` is provided, adds reservoir constraints for gold/elixir/DE
    based on initial stocks + hourly income.
    """
    model = cp_model.CpModel()

    if lpt_upper_bound is not None:
        horizon = int(lpt_upper_bound * horizon_buffer_pct)
    else:
        sum_dur = sum(j.duration_sec for j in jobs) + 1
        horizon = int(sum_dur * horizon_buffer_pct)
    # With resource constraints the horizon may need extending if a shortage
    # would otherwise force scheduling beyond the LPT bound.
    if resource_budget is not None:
        # Heuristic: expand to give the solver room to wait for income.
        horizon = max(horizon, int(sum(j.duration_sec for j in jobs) / max(builders, 1)) * 4)

    job_by_id = {j.id: j for j in jobs}
    interval_by_id: Dict[str, cp_model.IntervalVar] = {}
    start_by_id: Dict[str, cp_model.IntVar] = {}
    end_by_id: Dict[str, cp_model.IntVar] = {}

    for j in jobs:
        start = model.NewIntVar(0, horizon, f"s_{j.id}")
        end = model.NewIntVar(0, horizon, f"e_{j.id}")
        interval = model.NewIntervalVar(start, j.duration_sec, end, f"iv_{j.id}")
        start_by_id[j.id] = start
        end_by_id[j.id] = end
        interval_by_id[j.id] = interval

    # Precedence
    for j in jobs:
        for pid in j.prereq_ids:
            if pid in end_by_id:
                model.Add(start_by_id[j.id] >= end_by_id[pid])

    # Builder cumulative
    builder_intervals = [interval_by_id[j.id] for j in jobs if j.track == Track.BUILDER]
    if builder_intervals:
        # Demands all 1; capacity = builders.
        model.AddCumulative(builder_intervals, [1] * len(builder_intervals), builders)

    # Lab no-overlap
    lab_intervals = [interval_by_id[j.id] for j in jobs if j.track == Track.LAB]
    if lab_intervals:
        model.AddNoOverlap(lab_intervals)

    # Pet House no-overlap
    pet_intervals = [interval_by_id[j.id] for j in jobs if j.track == Track.PET_HOUSE]
    if pet_intervals:
        model.AddNoOverlap(pet_intervals)

    # Free track: precedence only (already handled). No machine constraint.

    # Resource constraints (optional). LPT makespan helps prune abundant resources.
    if resource_budget is not None:
        lpt_ub = lpt_upper_bound
        if lpt_ub is None:
            try:
                lpt_ub = lpt_schedule(jobs, builders=builders).makespan_sec
            except Exception:
                lpt_ub = horizon
        add_resource_constraints(model, jobs, start_by_id, resource_budget, horizon,
                                 lpt_makespan_sec=lpt_ub)

    # Always expose makespan for reporting
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(end_by_id.values()))

    if objective == "weighted_completion_time":
        # Minimize sum(weight_j * end_j) — drives high-value jobs early.
        # Scale weights down if necessary to keep the objective in int63.
        weights = {j.id: upgrade_weight(j) for j in jobs}
        # Estimate max term: max_weight * horizon. Keep total < 10^17.
        max_w = max(weights.values()) if weights else 1
        scale = 1
        while max_w * horizon * len(jobs) > 10**17 and scale < 10**6:
            scale *= 10
        terms = [(weights[j.id] // scale) * end_by_id[j.id] for j in jobs if weights[j.id] > 0]
        if terms:
            model.Minimize(sum(terms))
        else:
            model.Minimize(makespan)
    else:
        # Classic makespan minimization with safe tie-break.
        int_safe = 10**18
        primary_weight = max(1, min(int_safe // max(horizon, 1) // 2, (len(jobs) + 1) * (horizon + 1)))
        if primary_weight > 1 and primary_weight * horizon < int_safe:
            model.Minimize(primary_weight * makespan + sum(start_by_id.values()))
        else:
            model.Minimize(makespan)

    # Warm-start from a priority-list schedule matched to the objective.
    lpt_sched_for_fallback = None
    try:
        if objective == "weighted_completion_time":
            lpt_sched_for_fallback = lpt_schedule(
                jobs, builders=builders,
                priority="weighted", weight_fn=upgrade_weight,
            )
        else:
            lpt_sched_for_fallback = lpt_schedule(jobs, builders=builders)
        for it in lpt_sched_for_fallback.items:
            if it.job.id in start_by_id:
                model.AddHint(start_by_id[it.job.id], it.start_sec)
    except Exception:
        pass

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, str(status))

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Fallback to the priority-list schedule we built as the hint.
        if fallback_to_lpt and lpt_sched_for_fallback is not None:
            return CPSATResult(
                schedule=lpt_sched_for_fallback,
                solve_status=f"{status_name} (fell back to LPT)",
                solve_wall_seconds=solver.WallTime(),
                best_objective=lpt_sched_for_fallback.makespan_sec,
            )
        raise RuntimeError(f"CP-SAT failed: {status_name}")

    # Extract schedule
    scheduled: List[ScheduledJob] = []
    # Assign builder machine indices post-solve via earliest-available greedy.
    builder_free = [0] * builders
    # Walk jobs in start-time order; assign each builder job to the earliest free slot.
    builder_jobs_solved = sorted(
        [(solver.Value(start_by_id[j.id]), solver.Value(end_by_id[j.id]), j)
         for j in jobs if j.track == Track.BUILDER],
        key=lambda x: (x[0], x[1]),
    )
    for s, e, j in builder_jobs_solved:
        # find any builder whose free_time <= s
        candidates = [i for i in range(builders) if builder_free[i] <= s]
        if not candidates:
            # shouldn't happen if cumulative was respected; fallback to min
            i = min(range(builders), key=lambda x: builder_free[x])
        else:
            i = candidates[0]
        builder_free[i] = e
        scheduled.append(ScheduledJob(job=j, start_sec=s, end_sec=e, machine=i))

    for j in jobs:
        if j.track == Track.BUILDER:
            continue
        s = solver.Value(start_by_id[j.id])
        e = solver.Value(end_by_id[j.id])
        scheduled.append(ScheduledJob(job=j, start_sec=s, end_sec=e, machine=0))

    makespan_val = solver.Value(makespan)
    return CPSATResult(
        schedule=Schedule(items=scheduled, makespan_sec=makespan_val),
        solve_status=status_name,
        solve_wall_seconds=solver.WallTime(),
        best_objective=makespan_val,
    )
