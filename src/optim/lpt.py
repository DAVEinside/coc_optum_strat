"""Greedy list scheduler with precedence, supporting two priority rules:

- "longest" (default): LPT — among ready jobs, pick longest first. Good for makespan.
- "weighted": pick by descending strength weight first (then duration). Good for
  weighted-completion-time objectives where high-value jobs should run early.

Treats:
- Builder track as m identical machines (capacity-m cumulative resource).
- Lab as 1 machine.
- Pet House as 1 machine.
- Free track (walls, if included) — scheduled with no machine hold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from src.data.schema import Track, UpgradeJob


@dataclass
class ScheduledJob:
    job: UpgradeJob
    start_sec: int
    end_sec: int
    machine: int  # builder index 0..m-1, or 0 for single-machine tracks


@dataclass
class Schedule:
    items: List[ScheduledJob]
    makespan_sec: int

    @property
    def makespan_days(self) -> float:
        return self.makespan_sec / 86400


def lpt_schedule(
    jobs: List[UpgradeJob],
    builders: int,
    priority: str = "longest",
    weight_fn: Optional[Callable[[UpgradeJob], int]] = None,
) -> Schedule:
    """Greedy priority-rule scheduler respecting precedence.

    `priority`:
        - "longest"  : pick longest duration first (classic LPT)
        - "weighted" : pick highest weight_fn(job) first, tie-break by duration
    `weight_fn`: required when priority="weighted".
    """
    if priority == "weighted" and weight_fn is None:
        raise ValueError("priority='weighted' requires weight_fn")

    job_by_id = {j.id: j for j in jobs}
    # remaining unscheduled prereq counts
    remaining_prereqs: Dict[str, int] = {j.id: len(j.prereq_ids) for j in jobs}
    # children index for fast unlock
    children: Dict[str, List[str]] = {j.id: [] for j in jobs}
    for j in jobs:
        for p in j.prereq_ids:
            if p in children:
                children[p].append(j.id)

    # earliest time each job's prereqs are finished
    earliest_start: Dict[str, int] = {j.id: 0 for j in jobs}

    # machine end times
    builder_end = [0] * builders
    lab_end = [0]
    pet_end = [0]

    scheduled: List[ScheduledJob] = []
    # ready set: jobs whose all prereqs are done in our scheduling so far.
    ready: List[str] = [j.id for j in jobs if remaining_prereqs[j.id] == 0]

    completed_count = 0

    while ready or any(remaining_prereqs[j.id] > 0 for j in jobs if j.id not in {s.job.id for s in scheduled}):
        if not ready:
            # Defensive: if there's something not yet ready but we have nothing to do,
            # something is wrong with the DAG (cycle or missing prereq).
            unscheduled = [j.id for j in jobs if j.id not in {s.job.id for s in scheduled}]
            raise RuntimeError(f"LPT stuck — no ready jobs but {len(unscheduled)} unscheduled. Possible cycle.")

        if priority == "weighted":
            ready.sort(key=lambda jid: (-weight_fn(job_by_id[jid]), -job_by_id[jid].duration_sec))
        else:
            ready.sort(key=lambda jid: -job_by_id[jid].duration_sec)
        jid = ready.pop(0)
        j = job_by_id[jid]

        # Pick machine + start time
        if j.track == Track.BUILDER:
            # Earliest available builder
            min_builder = min(range(builders), key=lambda i: builder_end[i])
            start = max(builder_end[min_builder], earliest_start[jid])
            end = start + j.duration_sec
            builder_end[min_builder] = end
            machine = min_builder
        elif j.track == Track.LAB:
            start = max(lab_end[0], earliest_start[jid])
            end = start + j.duration_sec
            lab_end[0] = end
            machine = 0
        elif j.track == Track.PET_HOUSE:
            start = max(pet_end[0], earliest_start[jid])
            end = start + j.duration_sec
            pet_end[0] = end
            machine = 0
        else:  # FREE (walls) — no machine, but still gated by prereqs (if any)
            start = earliest_start[jid]
            end = start + j.duration_sec
            machine = 0

        scheduled.append(ScheduledJob(job=j, start_sec=start, end_sec=end, machine=machine))
        completed_count += 1

        # Unlock children
        for child_id in children.get(jid, []):
            earliest_start[child_id] = max(earliest_start[child_id], end)
            remaining_prereqs[child_id] -= 1
            if remaining_prereqs[child_id] == 0:
                ready.append(child_id)

    makespan = max((s.end_sec for s in scheduled), default=0)
    return Schedule(items=scheduled, makespan_sec=makespan)
