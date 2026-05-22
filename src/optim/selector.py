"""Apply a selection profile (YAML) to filter the full job list.

The user picks WHICH upgrades to do; the scheduler then orders only those.

YAML schema (one file per preset):

  target_th: 16
  starting_th: 15
  builders: 6

  heroes: all_max          # all_max | none | [list of names]
  defenses: all_max        # all_max | none | [list of building names]
  storages: all_max        # ditto
  army_buildings: all_max  # ditto
  resource_buildings: all_max
  troops:
    mode: all_max | whitelist | none
    whitelist: [Hog Rider, Healer, ...]   # used if mode==whitelist
  spells:
    mode: all_max | whitelist | none
    whitelist: [Rage Spell, Freeze Spell, ...]
  pets:
    mode: all_max | whitelist | none
    whitelist: [Frosty, Diggy, ...]
  walls:
    pct_to_next_level: 1.0   # 0.0 = skip walls, 1.0 = upgrade all, 0.5 = half
  town_hall: include          # include | skip
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Set

import yaml

from src.data.schema import Category, Track, UpgradeJob


_DEFENSE_NAMES = {
    "Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower",
    "Air Sweeper", "Hidden Tesla", "Bomb Tower", "X-Bow", "Inferno Tower",
    "Eagle Artillery", "Scattershot", "Spell Tower", "Monolith",
    "Ricochet Cannon", "Multi-Archer Tower", "Multi-Gear Tower",
    "Builder's Hut",
}
_STORAGE_NAMES = {
    "Gold Storage", "Elixir Storage", "Dark Elixir Storage",
    "Gold Mine", "Elixir Collector", "Dark Elixir Drill",
}
_ARMY_BUILDING_NAMES = {
    "Laboratory", "Spell Factory", "Dark Spell Factory",
    "Barracks", "Dark Barracks", "Army Camp", "Pet House",
    "Clan Castle",
}


def _base_name(name: str) -> str:
    # Strip " #N" instance suffix.
    if " #" in name:
        return name.split(" #", 1)[0]
    return name


def load_profile(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_profile(jobs: List[UpgradeJob], profile: dict) -> List[UpgradeJob]:
    """Filter jobs to only those allowed by the profile."""
    keep_ids: Set[str] = set()

    # 1) Pass-through buckets
    heroes_mode = profile.get("heroes", "all_max")
    defenses_mode = profile.get("defenses", "all_max")
    storages_mode = profile.get("storages", "all_max")
    army_mode = profile.get("army_buildings", "all_max")
    resource_mode = profile.get("resource_buildings", "all_max")
    troops_cfg = profile.get("troops", {"mode": "all_max"})
    spells_cfg = profile.get("spells", {"mode": "all_max"})
    pets_cfg = profile.get("pets", {"mode": "all_max"})
    walls_cfg = profile.get("walls", {"pct_to_next_level": 1.0})
    town_hall_cfg = profile.get("town_hall", "include")

    walls_pct = float(walls_cfg.get("pct_to_next_level", 1.0))

    def _allow_named(mode_or_list, name: str) -> bool:
        if mode_or_list == "all_max":
            return True
        if mode_or_list == "none":
            return False
        if isinstance(mode_or_list, list):
            return name in mode_or_list
        return False

    def _allow_cfg(cfg: dict, name: str) -> bool:
        mode = cfg.get("mode", "all_max")
        if mode == "all_max":
            return True
        if mode == "none":
            return False
        if mode == "whitelist":
            return name in cfg.get("whitelist", [])
        return False

    # 2) Decide per-job
    wall_jobs = [j for j in jobs if j.category == Category.WALL]
    n_walls_keep = int(round(walls_pct * len(wall_jobs)))
    walls_kept_ids = {j.id for j in wall_jobs[:n_walls_keep]}

    for j in jobs:
        base = _base_name(j.name)
        if j.category == Category.TOWN_HALL:
            if town_hall_cfg == "include":
                keep_ids.add(j.id)
            continue
        if j.category == Category.HERO:
            if _allow_named(heroes_mode, j.name):
                keep_ids.add(j.id)
            continue
        if j.category == Category.TROOP:
            if _allow_cfg(troops_cfg, j.name):
                keep_ids.add(j.id)
            continue
        if j.category == Category.SPELL:
            if _allow_cfg(spells_cfg, j.name):
                keep_ids.add(j.id)
            continue
        if j.category == Category.PET:
            if _allow_cfg(pets_cfg, j.name):
                keep_ids.add(j.id)
            continue
        if j.category == Category.WALL:
            if j.id in walls_kept_ids:
                keep_ids.add(j.id)
            continue
        if j.category == Category.BUILDING:
            if base in _DEFENSE_NAMES:
                if _allow_named(defenses_mode, base):
                    keep_ids.add(j.id)
                continue
            if base in _STORAGE_NAMES:
                # storages + collectors lumped here
                if base.endswith("Storage") and _allow_named(storages_mode, base):
                    keep_ids.add(j.id)
                elif (base.endswith("Mine") or base.endswith("Collector") or base.endswith("Drill")) \
                        and _allow_named(resource_mode, base):
                    keep_ids.add(j.id)
                continue
            if base in _ARMY_BUILDING_NAMES:
                if _allow_named(army_mode, base):
                    keep_ids.add(j.id)
                continue
            # Unknown building — keep by default if defenses are kept
            if _allow_named(defenses_mode, base):
                keep_ids.add(j.id)

    # 3) Trim prereq_ids to only those still in keep set; preserves intra-chain ordering.
    filtered: List[UpgradeJob] = []
    for j in jobs:
        if j.id not in keep_ids:
            continue
        new_prereqs = [p for p in j.prereq_ids if p in keep_ids]
        filtered.append(j.model_copy(update={"prereq_ids": new_prereqs}))

    return filtered
