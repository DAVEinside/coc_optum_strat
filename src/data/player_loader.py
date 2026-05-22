"""Generate UpgradeJobs from a PlayerState targeting a specific TH level.

Unlike the simpler `load_buildings_xlsx` (which assumes start = TH(X-1) max),
this loader uses the *player's actual current levels* as the starting state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .player import PlayerState
from .schema import Category, Resource, Track, UpgradeJob
from .xlsx_parser import parse_xlsx, instance_count, max_level_at_th


_RESOURCE_MAP = {
    "Gold": Resource.GOLD, "Elixir": Resource.ELIXIR, "Dark Elixir": Resource.DARK_ELIXIR,
    "DarkElixir": Resource.DARK_ELIXIR,
    "gold": Resource.GOLD, "elixir": Resource.ELIXIR, "dark_elixir": Resource.DARK_ELIXIR,
    "": Resource.NONE, None: Resource.NONE,
}


def _to_resource(r) -> Resource:
    return _RESOURCE_MAP.get(r, Resource.NONE)


def _map_track_for_troop(name: str) -> Track:
    # Pet recognition — pet names are returned by the JSON for type=73, kept separate.
    # By the time we receive a player's troop_dict, pets have already been separated.
    return Track.LAB


def jobs_from_player_state(
    state: PlayerState,
    target_th: int,
    json_path: Path,
    xlsx_path: Path,
    use_player_buildings: bool = False,
    fill_to_target_max: bool = True,
    include_walls: bool = False,
) -> List[UpgradeJob]:
    """Build UpgradeJobs from a player's current state to target_th max.

    Parameters:
      state            : parsed PlayerState (current levels)
      target_th        : TH the player wants to reach (e.g. 18)
      json_path        : troopUpgradeStats.json
      xlsx_path        : structs_data.xlsx
      use_player_buildings : if True, use player's actual building levels. If False,
                             assume all buildings start at (target_th-1) max — useful when
                             the player_state building mapping is unreliable.
      fill_to_target_max : if True, schedule upgrades to target_th max for every entity.

    Returns: List[UpgradeJob] ready for the scheduler.
    """
    jobs: List[UpgradeJob] = []
    starting_th = state.th_level or (target_th - 1)

    # --- Heroes (track=builder) ---
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    for entry in json_data:
        if entry.get("village") != "home":
            continue
        name = entry["name"]
        cat = entry.get("category", "troop")
        sub = entry.get("subCategory", cat)
        upgrade = entry.get("upgrade", {}) or {}
        cost_arr = upgrade.get("cost", []) or []
        time_arr = upgrade.get("time", []) or []
        resource = _to_resource(upgrade.get("resource"))
        min_level = entry.get("minLevel", 1)
        levels_arr = entry.get("levels", [])
        unlock_hall = (entry.get("unlock") or {}).get("hall", 1)

        if unlock_hall > target_th:
            continue
        if target_th - 1 >= len(levels_arr):
            continue
        target_max = levels_arr[target_th - 1] if levels_arr else 0
        if target_max == 0:
            continue

        # current level: lookup by name from the appropriate state dict
        if cat == "hero":
            current = state.heroes.get(name, levels_arr[max(unlock_hall - 1, 0)] or 0)
            our_cat = Category.HERO
            track = Track.BUILDER
        elif cat == "spell":
            current = state.spells.get(name, 0)
            our_cat = Category.SPELL
            track = Track.LAB
        elif cat == "equipment":
            continue  # out of scope v1
        elif cat == "troop":
            if sub == "pet":
                current = state.pets.get(name, 0)
                our_cat = Category.PET
                track = Track.PET_HOUSE
            else:
                current = state.troops.get(name, 0)
                our_cat = Category.TROOP
                track = Track.LAB
        else:
            continue

        if not fill_to_target_max:
            continue
        if current >= target_max:
            continue

        prev_id: Optional[str] = None
        for lvl in range(current, target_max):
            idx = lvl - min_level + 1  # upgrade.time[i] is for level (i+min_level) -> (i+min_level+1)
            idx -= 1  # 0-indexed (lvl -> lvl+1 uses time[lvl - min_level])
            if idx < 0 or idx >= len(time_arr):
                continue
            duration = int(time_arr[idx])
            cost = int(cost_arr[idx]) if idx < len(cost_arr) else 0
            # th_required: smallest TH whose levels[] >= lvl+1
            th_req = next((th for th in range(1, len(levels_arr) + 1)
                          if levels_arr[th - 1] >= lvl + 1), target_th)
            job_id = f"{name.replace(' ', '_').lower()}_{lvl}_to_{lvl+1}"
            jobs.append(UpgradeJob(
                id=job_id, name=name, category=our_cat,
                from_level=lvl, to_level=lvl + 1,
                duration_sec=duration, cost=cost, resource=resource,
                th_required=th_req,
                prereq_ids=[prev_id] if prev_id else [],
                track=track,
            ))
            prev_id = job_id

    # --- Buildings + walls + traps (from xlsx) ---
    bld_df = parse_xlsx(xlsx_path)

    for raw_name in bld_df["raw_name"].unique():
        # Optionally drop walls (player typically handles these manually)
        if raw_name == "walls" and not include_walls:
            continue
        end_lvl = max_level_at_th(bld_df, raw_name, target_th) or 0
        if end_lvl == 0:
            continue
        count = instance_count(raw_name, target_th)
        if count == 0:
            continue
        rows = bld_df[bld_df["raw_name"] == raw_name].set_index("level")
        display = rows.iloc[0]["building"]

        # Player's current levels for this building (if use_player_buildings)
        if use_player_buildings:
            player_levels = state.buildings.get(display, [])
            # Pad with starting_th max if fewer instances recorded
            start_max_at_pre = max_level_at_th(bld_df, raw_name, starting_th) or 0
            player_levels = list(player_levels) + [start_max_at_pre] * max(0, count - len(player_levels))
        else:
            start_max_at_pre = max_level_at_th(bld_df, raw_name, starting_th) or 0
            player_levels = [start_max_at_pre] * count

        # Walls subset for free track (don't inflate job count)
        if raw_name == "walls":
            count = min(count, 50)
            player_levels = player_levels[:count]

        category = {
            "town hall": Category.TOWN_HALL,
            "walls": Category.WALL,
        }.get(raw_name, Category.BUILDING)
        track = Track.FREE if raw_name == "walls" else Track.BUILDER

        for inst_idx, start_lvl in enumerate(player_levels, 1):
            if start_lvl >= end_lvl:
                continue
            instance_label = f"{display} #{inst_idx}" if count > 1 else display
            prev_id: Optional[str] = None
            for lvl in range(start_lvl + 1, end_lvl + 1):
                if lvl not in rows.index:
                    continue
                r = rows.loc[lvl]
                duration = int(r["duration_sec"]) if pd.notna(r["duration_sec"]) else 0
                cost = int(r["cost"]) if pd.notna(r["cost"]) else 0
                th_req = int(r["th_required"]) if pd.notna(r["th_required"]) else target_th
                resource = _to_resource(r["resource"])
                job_id = f"{raw_name.replace(' ', '_')}_{inst_idx}_{lvl-1}_to_{lvl}"
                jobs.append(UpgradeJob(
                    id=job_id, name=instance_label, category=category,
                    from_level=lvl - 1, to_level=lvl,
                    duration_sec=duration, cost=cost, resource=resource,
                    th_required=th_req,
                    prereq_ids=[prev_id] if prev_id else [],
                    track=track,
                ))
                prev_id = job_id

    return jobs
