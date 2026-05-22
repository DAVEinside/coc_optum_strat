"""Precedence-graph utilities for UpgradeJob lists.

Currently exposes a single helper used by the app: `add_town_hall_gate`,
which links every TH(X)-required upgrade to the TH(X-1 -> X) upgrade so the
scheduler waits for the Town Hall to finish before TH(X)-tier work begins.
"""
from __future__ import annotations

from typing import List

from .schema import Category, UpgradeJob


def add_town_hall_gate(jobs: List[UpgradeJob], target_th: int) -> List[UpgradeJob]:
    """For every job whose th_required == target_th, add a precedence on the TH upgrade.

    Ensures upgrades requiring TH(N) start only after the TH(N-1 -> N) upgrade finishes.
    """
    th_job_id = None
    for j in jobs:
        if j.category == Category.TOWN_HALL and j.to_level == target_th:
            th_job_id = j.id
            break
    if th_job_id is None:
        return jobs

    out: List[UpgradeJob] = []
    for j in jobs:
        if j.id == th_job_id:
            out.append(j)
            continue
        if j.th_required >= target_th and not j.prereq_ids:
            j = j.model_copy(update={"prereq_ids": [th_job_id]})
        out.append(j)
    return out
