"""Parse Supercell-format player state (my_stats.txt) into PlayerState.

The game encodes entities as `data` integers of the form `type * 1_000_000 + entity_id`:
- type 1  : home village buildings
- type 4  : troops + siege machines (home village)
- type 8  : obstacles (cosmetic, skipped)
- type 12 : traps
- type 18 : decorations (cosmetic)
- type 26 : spells
- type 28 : heroes
- type 52 : skins (cosmetic)
- type 60 : sceneries (cosmetic)
- type 73 : pets
- type 82 : hero house parts (cosmetic)
- type 90 : equipment
- type 93 : helpers (workers)
- type 107: guardians (Builder Base pets)

For troops/heroes/spells/pets/equipment we read names directly from the existing JSON
(`troopUpgradeStats.json`) via the `id` field. For buildings we use a hardcoded table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# --- Type prefixes ---
TYPE_BUILDING = 1
TYPE_TROOP = 4
TYPE_TRAP = 12
TYPE_SPELL = 26
TYPE_HERO = 28
TYPE_PET = 73
TYPE_EQUIPMENT = 90


def _split_data(data_int: int) -> Tuple[int, int]:
    return data_int // 1_000_000, data_int % 1_000_000


# --- Building ID -> name mapping (home village only) ---
# Best-effort based on community ID tables. Numbers Supercell hasn't documented;
# correct if needed.
BUILDING_BY_ID: Dict[int, str] = {
    0: "Cannon", 1: "Archer Tower", 2: "Mortar", 3: "Air Defense",
    4: "Wizard Tower", 5: "Gold Storage", 6: "Elixir Storage",
    7: "Gold Mine", 8: "Elixir Collector", 9: "Air Sweeper",
    10: "Wall", 11: "Hidden Tesla", 12: "Bomb Tower",
    13: "Town Hall",
    14: "X-Bow", 15: "Inferno Tower", 16: "Eagle Artillery",
    17: "Builder's Hut", 18: "Army Camp", 19: "Barracks",
    20: "Dark Barracks", 21: "Laboratory", 22: "Spell Factory",
    23: "Dark Spell Factory", 24: "Clan Castle", 25: "Dark Elixir Drill",
    26: "Dark Elixir Storage", 27: "Scattershot", 28: "Workshop",
    29: "Pet House", 32: "Hero Hall", 59: "Blacksmith",
    67: "Spell Tower", 68: "Monolith", 70: "Multi-Archer Tower",
    71: "Ricochet Cannon", 72: "Multi-Gear Tower",
    77: "Firespitter", 79: "Revenge Tower",
    84: "Super Wizard Tower", 85: "Roaster",
    86: "Airbomb", 89: "Lava Launcher",
    93: "Giga Cannon", 97: "Town Hall Weapon", 102: "TH18 Weapon",
}

TRAP_BY_ID: Dict[int, str] = {
    0: "Bombs", 1: "Spring Traps", 2: "Giant Bomb",
    5: "Air Bomb", 6: "Seeking Air Mine", 8: "Skeleton Trap",
    10: "Tornado Trap", 16: "Giga Bomb", 20: "Mega Mine",
}


def _load_name_lookups(json_path: Path) -> Dict[int, Dict[int, str]]:
    """Build {type_prefix: {entity_id: name}} from the JSON repo."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    lookups: Dict[int, Dict[int, str]] = {
        TYPE_TROOP: {}, TYPE_SPELL: {}, TYPE_HERO: {},
        TYPE_PET: {}, TYPE_EQUIPMENT: {},
    }
    for entry in data:
        if entry.get("village") != "home":
            continue
        cat = entry.get("category", "")
        sub = entry.get("subCategory", "")
        eid = entry.get("id")
        name = entry.get("name", "")
        if cat == "hero":
            lookups[TYPE_HERO][eid] = name
        elif cat == "spell":
            lookups[TYPE_SPELL][eid] = name
        elif cat == "equipment":
            lookups[TYPE_EQUIPMENT][eid] = name
        elif cat == "troop":
            if sub == "pet":
                lookups[TYPE_PET][eid] = name
            else:
                lookups[TYPE_TROOP][eid] = name
    return lookups


@dataclass
class PlayerState:
    """Player's current state, parsed from Supercell my_stats data."""
    th_level: Optional[int] = None
    heroes: Dict[str, int] = field(default_factory=dict)             # name -> current level
    troops: Dict[str, int] = field(default_factory=dict)
    spells: Dict[str, int] = field(default_factory=dict)
    pets: Dict[str, int] = field(default_factory=dict)
    equipment: Dict[str, int] = field(default_factory=dict)
    buildings: Dict[str, List[int]] = field(default_factory=dict)    # name -> [levels for each instance]
    traps: Dict[str, List[int]] = field(default_factory=dict)
    upgrades_in_progress: List[str] = field(default_factory=list)    # things being upgraded NOW

    def hero_max(self) -> int:
        return max(self.heroes.values()) if self.heroes else 0

    def summary(self) -> str:
        return (f"TH{self.th_level} | heroes={len(self.heroes)} (max L{self.hero_max()}) | "
                f"troops={len(self.troops)} | spells={len(self.spells)} | "
                f"pets={len(self.pets)} | buildings={sum(len(v) for v in self.buildings.values())} instances "
                f"({len(self.buildings)} types)")


def parse_player_state_from_text(raw: str, json_repo_path: Path) -> PlayerState:
    """Parse my_stats.txt content (as a string) into PlayerState.

    The Supercell payload is JSON, sometimes preceded by a TSV-style row number
    like `1\\t{...}`. We locate the first '{' and parse from there.
    """
    raw = raw.strip()
    if not raw.startswith("{"):
        idx = raw.find("{")
        if idx >= 0:
            raw = raw[idx:]
    if not raw:
        raise ValueError("Empty player data — paste or upload your in-game share.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Couldn't parse as JSON: {e}") from e

    lookups = _load_name_lookups(json_repo_path)
    state = PlayerState()

    # --- buildings: aggregate {data: count} pairs and timer entries ---
    bld_list = data.get("buildings", []) or []
    for entry in bld_list:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_BUILDING:
            continue
        name = BUILDING_BY_ID.get(eid, f"Building_{eid}")
        lvl = entry.get("lvl")
        cnt = entry.get("cnt", 1)
        if lvl is not None:
            state.buildings.setdefault(name, []).extend([lvl] * cnt)
        if entry.get("timer"):
            state.upgrades_in_progress.append(f"{name} (in progress)")

    # --- traps ---
    for entry in data.get("traps", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_TRAP:
            continue
        name = TRAP_BY_ID.get(eid, f"Trap_{eid}")
        lvl = entry.get("lvl")
        cnt = entry.get("cnt", 1)
        if lvl is not None:
            state.traps.setdefault(name, []).extend([lvl] * cnt)

    # --- heroes / troops / spells / pets / equipment via JSON lookup ---
    for entry in data.get("heroes", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_HERO:
            continue
        name = lookups[TYPE_HERO].get(eid)
        if name and entry.get("lvl") is not None:
            state.heroes[name] = entry["lvl"]
        if entry.get("timer"):
            state.upgrades_in_progress.append(f"{name} (in progress)")

    for entry in data.get("units", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_TROOP:
            continue
        name = lookups[TYPE_TROOP].get(eid)
        if name and entry.get("lvl") is not None:
            state.troops[name] = entry["lvl"]

    # Siege machines are also under "siege_machines" with type=4
    for entry in data.get("siege_machines", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_TROOP:
            continue
        name = lookups[TYPE_TROOP].get(eid)
        if name and entry.get("lvl") is not None:
            state.troops[name] = entry["lvl"]

    for entry in data.get("spells", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_SPELL:
            continue
        name = lookups[TYPE_SPELL].get(eid)
        if name and entry.get("lvl") is not None:
            state.spells[name] = entry["lvl"]

    for entry in data.get("pets", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_PET:
            continue
        name = lookups[TYPE_PET].get(eid)
        if name and entry.get("lvl") is not None:
            state.pets[name] = entry["lvl"]

    for entry in data.get("equipment", []) or []:
        d = entry.get("data")
        if d is None:
            continue
        type_prefix, eid = _split_data(d)
        if type_prefix != TYPE_EQUIPMENT:
            continue
        name = lookups[TYPE_EQUIPMENT].get(eid)
        if name and entry.get("lvl") is not None:
            state.equipment[name] = entry["lvl"]

    # --- TH level inference ---
    if "Town Hall" in state.buildings and state.buildings["Town Hall"]:
        state.th_level = max(state.buildings["Town Hall"])
    else:
        state.th_level = _infer_th_from_heroes(state.heroes)

    return state


def parse_player_state(stats_path: Path, json_repo_path: Path) -> PlayerState:
    """Parse my_stats.txt from a file path."""
    raw = stats_path.read_text(encoding="utf-8", errors="replace")
    return parse_player_state_from_text(raw, json_repo_path)


# --- TH inference from heroes ---
# Max hero levels per TH from current game (TH7=10 BK, ..., TH18 = 105).
# We pick the LOWEST TH whose max is >= the player's max hero level.
_HERO_MAX_AT_TH = {
    "Barbarian King": [0,0,0,0,0,0,10,20,30,40,50,65,75,85,90,95,100,105],
    "Archer Queen":   [0,0,0,0,0,0,0,0,30,40,50,65,75,85,90,95,100,105],
    "Grand Warden":   [0,0,0,0,0,0,0,0,0,0,20,40,50,55,65,75,80,85],
    "Royal Champion": [0,0,0,0,0,0,0,0,0,0,0,0,25,30,40,50,55,60],
}


def _infer_th_from_heroes(heroes: Dict[str, int]) -> Optional[int]:
    """Smallest TH that allows the highest observed hero level for each hero we recognize."""
    th_floor = 1
    for name, lvl in heroes.items():
        caps = _HERO_MAX_AT_TH.get(name)
        if not caps:
            continue
        for th in range(1, len(caps) + 1):
            if caps[th - 1] >= lvl:
                th_floor = max(th_floor, th)
                break
    return th_floor if th_floor > 1 else None
