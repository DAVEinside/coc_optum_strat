"""Loaders that produce UpgradeJob records from various sources.

Sources:
- `troopUpgradeStats.json` (existing data repo) — troops, spells, heroes, equipment.
- `structs_data.xlsx` (wiki-sourced) — buildings, traps, walls, TH itself.
- Manual CSV (legacy fallback) — buildings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from .schema import Category, Resource, Track, UpgradeJob
from .xlsx_parser import parse_xlsx, instance_count, max_level_at_th


# --- Resource string normalization (data repo uses mixed case / spaces) ---
_RESOURCE_MAP = {
    "Gold": Resource.GOLD,
    "Elixir": Resource.ELIXIR,
    "Dark Elixir": Resource.DARK_ELIXIR,
    "DarkElixir": Resource.DARK_ELIXIR,
    "gold": Resource.GOLD,
    "elixir": Resource.ELIXIR,
    "dark_elixir": Resource.DARK_ELIXIR,
    "": Resource.NONE,
    None: Resource.NONE,
}


def _to_resource(r: Optional[str]) -> Resource:
    return _RESOURCE_MAP.get(r, Resource.NONE)


# --- Map data-repo category → our Category & Track ---
def _map_category_track(category: str, sub: str, name: str) -> tuple[Category, Track]:
    if category == "hero":
        return Category.HERO, Track.BUILDER
    if category == "troop":
        # Pets are categorized as troop with subCategory='pet' or similar.
        # We treat pet upgrades as PET_HOUSE track (independent of builders & lab).
        if sub == "pet" or "pet" in name.lower():
            return Category.PET, Track.PET_HOUSE
        return Category.TROOP, Track.LAB
    if category == "spell":
        return Category.SPELL, Track.LAB
    # equipment is out of scope for v1
    return Category.TROOP, Track.LAB


def load_troops_spells_heroes(
    json_path: Path,
    target_th: int,
    starting_th: int,
) -> List[UpgradeJob]:
    """Build per-level upgrade jobs for the transition starting_th -> target_th.

    Each entity has:
      - levels[i]: max level at TH i+1
      - upgrade.time[i] / .cost[i]: for upgrade from level (i+minLevel) to (i+minLevel+1)
      - upgrade.resource: single resource type
      - unlock.hall: TH at which the entity is unlocked

    We emit one UpgradeJob per level transition between the starting_th max and the target_th max.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs: List[UpgradeJob] = []

    for entity in data:
        # skip equipment (no time arrays, separate progression)
        if entity.get("category") == "equipment":
            continue
        # skip builder base entities (out of scope v1)
        if entity.get("village") != "home":
            continue

        name = entity["name"]
        category = entity.get("category", "troop")
        sub = entity.get("subCategory", category)
        cat, track = _map_category_track(category, sub, name)

        levels_arr = entity.get("levels", [])
        upgrade = entity.get("upgrade", {}) or {}
        cost_arr = upgrade.get("cost", []) or []
        time_arr = upgrade.get("time", []) or []
        resource = _to_resource(upgrade.get("resource"))
        min_level = entity.get("minLevel", 1)

        unlock_hall = (entity.get("unlock") or {}).get("hall", 1)

        # levels[] is 0-indexed by TH-1. We need indices for starting_th-1 and target_th-1.
        if starting_th - 1 >= len(levels_arr) or target_th - 1 >= len(levels_arr):
            continue
        start_lvl = levels_arr[starting_th - 1]
        end_lvl = levels_arr[target_th - 1]
        if end_lvl <= start_lvl:
            # nothing to upgrade for this entity in this transition
            continue
        # entity not unlocked yet
        if unlock_hall > target_th:
            continue

        # Emit one job per level transition: (lvl -> lvl+1) for lvl in [start_lvl..end_lvl-1]
        # upgrade.time[i] is the time to upgrade from level (i+minLevel) to (i+minLevel+1).
        # So for transition L -> L+1, index = L - minLevel.
        prev_job_id: Optional[str] = None
        for lvl in range(start_lvl, end_lvl):
            idx = lvl - min_level
            if idx < 0 or idx >= len(time_arr):
                # data inconsistency — skip
                continue
            job_id = f"{name.replace(' ', '_').lower()}_{lvl}_to_{lvl+1}"
            duration = int(time_arr[idx])
            cost = int(cost_arr[idx]) if idx < len(cost_arr) else 0

            # th_required for THIS transition: max(unlock_hall, lowest TH at which this level is reachable).
            # Approximation: any level above starting_th max requires target_th.
            th_req = target_th if lvl >= levels_arr[starting_th - 1] else starting_th

            jobs.append(UpgradeJob(
                id=job_id,
                name=name,
                category=cat,
                from_level=lvl,
                to_level=lvl + 1,
                duration_sec=duration,
                cost=cost,
                resource=resource,
                th_required=th_req,
                prereq_ids=[prev_job_id] if prev_job_id else [],
                track=track,
            ))
            prev_job_id = job_id

    return jobs


def load_buildings_csv(
    csv_path: Path,
    target_th: int,
    starting_th: int,
) -> List[UpgradeJob]:
    """Load building upgrade data from a manually-curated CSV.

    Expected columns:
      name, category (building|town_hall|wall),
      from_level, to_level, duration_sec, cost, resource, th_required, track

    `track` is `builder` for almost everything except walls which are `free`,
    and `town_hall` is `builder` (it consumes a builder while upgrading).
    """
    df = pd.read_csv(csv_path)

    # Filter to rows whose th_required is reachable in this transition.
    # (e.g. for TH15->TH16 we include rows with th_required in {15, 16})
    df = df[(df["th_required"] >= starting_th) & (df["th_required"] <= target_th)].copy()

    jobs: List[UpgradeJob] = []

    # Build serial chains per building so level k must precede level k+1.
    df = df.sort_values(["name", "from_level"]).reset_index(drop=True)
    prev_by_name: dict[str, str] = {}
    for _, row in df.iterrows():
        name = row["name"]
        cat_str = str(row["category"]).lower()
        category = {
            "building": Category.BUILDING,
            "town_hall": Category.TOWN_HALL,
            "wall": Category.WALL,
        }.get(cat_str, Category.BUILDING)

        track_str = str(row["track"]).lower()
        track = {
            "builder": Track.BUILDER,
            "free": Track.FREE,
        }.get(track_str, Track.BUILDER)

        resource = _to_resource(row["resource"])
        job_id = f"{name.replace(' ', '_').lower()}_{row['from_level']}_to_{row['to_level']}"
        prev_id = prev_by_name.get(name)
        jobs.append(UpgradeJob(
            id=job_id,
            name=name,
            category=category,
            from_level=int(row["from_level"]),
            to_level=int(row["to_level"]),
            duration_sec=int(row["duration_sec"]),
            cost=int(row["cost"]),
            resource=resource,
            th_required=int(row["th_required"]),
            prereq_ids=[prev_id] if prev_id else [],
            track=track,
        ))
        prev_by_name[name] = job_id

    return jobs


_BUILDING_CATEGORY: dict[str, Category] = {
    "town hall": Category.TOWN_HALL,
    "walls": Category.WALL,
    # Traps are normal buildings (use a builder, take real time)
}

# Only walls are on the free track — they upgrade instantly with no builder hold.
# Traps consume a builder and have build times of up to ~13 days.
_FREE_TRACK_NAMES = {"walls"}


def load_buildings_xlsx(
    xlsx_path: Path,
    target_th: int,
    starting_th: int,
    walls_subset: int = 50,
) -> List[UpgradeJob]:
    """Build UpgradeJobs from the wiki-sourced xlsx for the given TH transition.

    For each building present at `target_th`, we emit one UpgradeJob per
    (instance, level transition) where the level is gated on `starting_th` -> `target_th`.

    `walls_subset`: limit number of wall instances (default 50). 325 walls would inflate
    job count without affecting makespan since walls are on the free track.
    """
    df = parse_xlsx(xlsx_path)

    jobs: List[UpgradeJob] = []

    for raw_name in df["raw_name"].unique():
        start_lvl = max_level_at_th(df, raw_name, starting_th) or 0
        end_lvl = max_level_at_th(df, raw_name, target_th) or 0
        if end_lvl <= start_lvl:
            continue
        # Building must exist at target TH
        count = instance_count(raw_name, target_th)
        if count == 0:
            continue
        # Walls / traps subset cap (they're on free track, don't affect makespan)
        if raw_name == "walls":
            count = min(count, walls_subset)

        rows = df[df["raw_name"] == raw_name].set_index("level")
        category = _BUILDING_CATEGORY.get(raw_name, Category.BUILDING)
        track = Track.FREE if raw_name in _FREE_TRACK_NAMES else Track.BUILDER

        for instance in range(1, count + 1):
            instance_label = f"{rows.iloc[0]['building']} #{instance}" if count > 1 else rows.iloc[0]['building']
            prev_id: Optional[str] = None
            for lvl in range(start_lvl + 1, end_lvl + 1):
                if lvl not in rows.index:
                    continue
                r = rows.loc[lvl]
                duration = int(r["duration_sec"]) if pd.notna(r["duration_sec"]) else 0
                cost = int(r["cost"]) if pd.notna(r["cost"]) else 0
                th_req = int(r["th_required"]) if pd.notna(r["th_required"]) else target_th
                resource = _to_resource(r["resource"])
                job_id = f"{raw_name.replace(' ', '_')}_{instance}_{lvl-1}_to_{lvl}"
                jobs.append(UpgradeJob(
                    id=job_id,
                    name=instance_label,
                    category=category,
                    from_level=lvl - 1,
                    to_level=lvl,
                    duration_sec=duration,
                    cost=cost,
                    resource=resource,
                    th_required=th_req,
                    prereq_ids=[prev_id] if prev_id else [],
                    track=track,
                ))
                prev_id = job_id

    return jobs


def add_town_hall_gate(jobs: List[UpgradeJob], target_th: int) -> List[UpgradeJob]:
    """For every job whose th_required == target_th, add a precedence on the TH upgrade.

    This ensures that any upgrade requiring TH16 starts only AFTER the TH15->TH16 upgrade.
    """
    th_job_id = None
    for j in jobs:
        if j.category == Category.TOWN_HALL and j.to_level == target_th:
            th_job_id = j.id
            break
    if th_job_id is None:
        return jobs  # no TH upgrade in this dataset; nothing to gate

    out: List[UpgradeJob] = []
    for j in jobs:
        if j.id == th_job_id:
            out.append(j)
            continue
        # Only the FIRST level transition of an entity needs the explicit TH gate;
        # subsequent ones inherit transitively through the entity's intra-chain.
        if j.th_required >= target_th and not j.prereq_ids:
            j = j.model_copy(update={"prereq_ids": [th_job_id]})
        out.append(j)
    return out


def jobs_to_dataframe(jobs: Iterable[UpgradeJob]) -> pd.DataFrame:
    return pd.DataFrame([j.model_dump() for j in jobs])
