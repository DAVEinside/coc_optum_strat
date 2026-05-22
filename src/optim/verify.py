"""Verification asserts for a Schedule.

Call `verify_schedule(schedule, jobs, builders)` after solving.
Raises AssertionError with a descriptive message on first violation.
"""
from __future__ import annotations

from collections import defaultdict
from typing import List

from src.data.schema import Track, UpgradeJob
from src.optim.lpt import Schedule


def verify_schedule(schedule: Schedule, jobs: List[UpgradeJob], builders: int) -> dict:
    """Check that the schedule respects all constraints.

    Returns a dict of metrics: { 'jobs_scheduled', 'makespan_sec', 'lower_bound_sec' }.
    Raises AssertionError if any constraint is violated.
    """
    by_id = {j.id: j for j in jobs}
    items_by_id = {it.job.id: it for it in schedule.items}

    # 1. All jobs scheduled exactly once
    assert len(items_by_id) == len(jobs), (
        f"Scheduled {len(items_by_id)} jobs but expected {len(jobs)}"
    )

    # 2. Each scheduled job's duration matches the underlying job's duration
    for it in schedule.items:
        expected = it.job.duration_sec
        got = it.end_sec - it.start_sec
        assert got == expected, (
            f"Job {it.job.id}: end-start={got} but duration={expected}"
        )

    # 3. Precedence: end(parent) <= start(child)
    for j in jobs:
        child_item = items_by_id[j.id]
        for pid in j.prereq_ids:
            if pid not in items_by_id:
                continue
            parent_item = items_by_id[pid]
            assert parent_item.end_sec <= child_item.start_sec, (
                f"Precedence violation: {pid}.end={parent_item.end_sec} > "
                f"{j.id}.start={child_item.start_sec}"
            )

    # 4. No-overlap per builder machine
    by_builder = defaultdict(list)
    for it in schedule.items:
        if it.job.track == Track.BUILDER:
            by_builder[it.machine].append(it)
    for bi, items in by_builder.items():
        items_sorted = sorted(items, key=lambda x: x.start_sec)
        for a, b in zip(items_sorted, items_sorted[1:]):
            assert a.end_sec <= b.start_sec, (
                f"Builder {bi} overlap: {a.job.id} [{a.start_sec},{a.end_sec}] "
                f"vs {b.job.id} [{b.start_sec},{b.end_sec}]"
            )
    assert len(by_builder) <= builders, (
        f"Used {len(by_builder)} builder slots, expected at most {builders}"
    )

    # 5. Lab and pet house no-overlap (single machine each)
    for track in (Track.LAB, Track.PET_HOUSE):
        items_t = sorted(
            [it for it in schedule.items if it.job.track == track],
            key=lambda x: x.start_sec,
        )
        for a, b in zip(items_t, items_t[1:]):
            assert a.end_sec <= b.start_sec, (
                f"{track.value} overlap: {a.job.id} [{a.start_sec},{a.end_sec}] "
                f"vs {b.job.id} [{b.start_sec},{b.end_sec}]"
            )

    # 6. Cumulative builders check: at any instant <= `builders` concurrent builder jobs
    # Sweep-line.
    events = []
    for it in schedule.items:
        if it.job.track == Track.BUILDER:
            events.append((it.start_sec, +1))
            events.append((it.end_sec, -1))
    events.sort()
    active = 0
    max_active = 0
    for t, delta in events:
        active += delta
        max_active = max(max_active, active)
    assert max_active <= builders, (
        f"At peak, {max_active} builders active, but only {builders} available"
    )

    # 7. Lower-bound sanity
    total_builder_work = sum(j.duration_sec for j in jobs if j.track == Track.BUILDER)
    total_lab_work = sum(j.duration_sec for j in jobs if j.track == Track.LAB)
    total_pet_work = sum(j.duration_sec for j in jobs if j.track == Track.PET_HOUSE)

    lb_builder = total_builder_work / builders if builders > 0 else 0
    lb_lab = total_lab_work
    lb_pet = total_pet_work
    cumulative_lb = max(lb_builder, lb_lab, lb_pet)
    assert schedule.makespan_sec >= cumulative_lb - 1, (
        f"Makespan {schedule.makespan_sec} below lower bound {cumulative_lb}"
    )

    return {
        "jobs_scheduled": len(items_by_id),
        "makespan_sec": schedule.makespan_sec,
        "makespan_days": schedule.makespan_days,
        "lower_bound_sec": int(cumulative_lb),
        "lower_bound_days": cumulative_lb / 86400,
        "gap_to_lb_pct": 100 * (schedule.makespan_sec - cumulative_lb) / max(cumulative_lb, 1),
    }
