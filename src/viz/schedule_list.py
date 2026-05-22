"""Human-readable upgrade list views of a Schedule.

Two output styles:
- `by_builder()`: per-track timeline, one entry per upgrade with start/end times.
- `chronological()`: a single sequence of events, sorted by start time.

Times are reported in days from t=0 (the start of the transition).
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from src.data.schema import Track
from src.optim.lpt import Schedule


def _fmt_days(sec: int) -> str:
    d = sec / 86400
    if d < 1:
        return f"{sec/3600:4.1f}h"
    return f"{d:5.1f}d"


def by_builder(schedule: Schedule) -> Dict[str, List[dict]]:
    """Return {track_label: [entry, ...]} where entries are sorted by start time.

    Track labels: "Builder 1", "Builder 2", ..., "Laboratory", "Pet House", "Walls (free)".
    """
    by_track: Dict[str, List[dict]] = {}
    for it in schedule.items:
        j = it.job
        if j.track == Track.BUILDER:
            label = f"Builder {it.machine + 1}"
        elif j.track == Track.LAB:
            label = "Laboratory"
        elif j.track == Track.PET_HOUSE:
            label = "Pet House"
        else:
            label = "Walls (free)"
        by_track.setdefault(label, []).append({
            "name": j.name,
            "from_level": j.from_level,
            "to_level": j.to_level,
            "start_sec": it.start_sec,
            "end_sec": it.end_sec,
            "duration_sec": j.duration_sec,
            "category": j.category.value,
            "resource": j.resource.value,
            "cost": j.cost,
        })
    for k in by_track:
        by_track[k].sort(key=lambda x: x["start_sec"])
    return by_track


def chronological(schedule: Schedule) -> List[dict]:
    """Return a single list of upgrades sorted by start time."""
    rows = []
    for it in schedule.items:
        j = it.job
        if j.track == Track.BUILDER:
            machine = f"Builder {it.machine + 1}"
        elif j.track == Track.LAB:
            machine = "Laboratory"
        elif j.track == Track.PET_HOUSE:
            machine = "Pet House"
        else:
            machine = "Walls (free)"
        rows.append({
            "machine": machine,
            "name": j.name,
            "from_level": j.from_level,
            "to_level": j.to_level,
            "start_sec": it.start_sec,
            "end_sec": it.end_sec,
            "duration_sec": j.duration_sec,
            "category": j.category.value,
            "resource": j.resource.value,
            "cost": j.cost,
        })
    rows.sort(key=lambda x: (x["start_sec"], x["machine"]))
    return rows


def to_dataframe(schedule: Schedule) -> pd.DataFrame:
    df = pd.DataFrame(chronological(schedule))
    df["start_day"] = (df["start_sec"] / 86400).round(2)
    df["end_day"] = (df["end_sec"] / 86400).round(2)
    df["duration"] = df["duration_sec"].apply(_fmt_days)
    return df[["start_day", "end_day", "machine", "name", "from_level", "to_level", "duration", "category", "cost", "resource"]]


def print_by_builder(schedule: Schedule, max_per_track: int = 30) -> None:
    """Print a per-track upgrade plan, ordered start-time ascending."""
    tracks = by_builder(schedule)
    # Order: builders 1..N, then Laboratory, then Pet House, then Walls
    builder_keys = sorted([k for k in tracks if k.startswith("Builder")],
                         key=lambda x: int(x.split()[-1]))
    ordered = builder_keys + [k for k in ("Laboratory", "Pet House", "Walls (free)") if k in tracks]

    for track in ordered:
        items = tracks[track]
        print(f"\n=== {track}  ({len(items)} upgrades, finishes day {items[-1]['end_sec']/86400:.1f}) ===")
        shown = items[:max_per_track]
        for i, it in enumerate(shown, 1):
            start_d = it["start_sec"] / 86400
            end_d = it["end_sec"] / 86400
            print(f" {i:3d}. day {start_d:6.1f} -> {end_d:6.1f} ({_fmt_days(it['duration_sec'])})  "
                  f"{it['name']:24s} L{it['from_level']:<3d}->L{it['to_level']:<3d}  "
                  f"({it['category']}, {it['cost']:>10,} {it['resource']})")
        if len(items) > max_per_track:
            print(f"     ... {len(items) - max_per_track} more")


def to_markdown(schedule: Schedule) -> str:
    """Generate a Markdown report of the schedule, suitable for sharing."""
    tracks = by_builder(schedule)
    builder_keys = sorted([k for k in tracks if k.startswith("Builder")],
                         key=lambda x: int(x.split()[-1]))
    ordered = builder_keys + [k for k in ("Laboratory", "Pet House", "Walls (free)") if k in tracks]

    lines = [f"# Upgrade Plan — makespan {schedule.makespan_days:.1f} days\n"]
    for track in ordered:
        items = tracks[track]
        lines.append(f"\n## {track}  ({len(items)} upgrades, finishes day {items[-1]['end_sec']/86400:.1f})\n")
        lines.append("| # | Day start | Day end | Upgrade | Levels | Duration | Resource |")
        lines.append("|---:|---:|---:|---|---|---|---|")
        for i, it in enumerate(items, 1):
            sd = it["start_sec"] / 86400
            ed = it["end_sec"] / 86400
            lines.append(
                f"| {i} | {sd:.1f} | {ed:.1f} | {it['name']} | "
                f"L{it['from_level']}->L{it['to_level']} | {_fmt_days(it['duration_sec']).strip()} | "
                f"{it['cost']:,} {it['resource']} |"
            )
    return "\n".join(lines)
