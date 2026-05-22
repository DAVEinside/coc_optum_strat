"""Strength weights per upgrade — drives weighted-completion-time scheduling.

Each upgrade contributes some "value" toward base/army/hero strength. The scheduler
prioritizes high-weight upgrades early so the player gains strength fastest.

Weights are categorical with name-based overrides for key defenses. They're a coarse
heuristic — for v1 the goal is just to push heroes/troops/spells/key defenses ahead of
storages and resource buildings, not to be precisely accurate per-level.
"""
from __future__ import annotations

from typing import Dict

from src.data.schema import Category, UpgradeJob


# Categorical default weights
WEIGHT_HERO = 100         # Heroes: huge impact on both offense and defense
WEIGHT_KEY_DEFENSE = 70   # Eagle, Inferno, Scattershot, Monolith, Spell Tower, etc.
WEIGHT_TROOP = 55         # Lab troops directly drive attack strength
WEIGHT_SPELL = 45         # Spells shape attacks
WEIGHT_PET = 40           # Pets buff heroes
WEIGHT_STD_DEFENSE = 25   # Cannons, ATs, Mortars, ADs, WTs, X-Bows, Hidden Teslas, Bomb Towers
WEIGHT_ARMY_BLDG = 18     # Army Camp (more troops), Barracks (no impact till lab)
WEIGHT_LAB_HOUSE = 15     # Lab building (unlocks higher troop levels) and Pet House (unlocks pets)
WEIGHT_TOWN_HALL = 10     # TH itself: needed but doesn't directly boost strength
WEIGHT_STORAGE = 3        # Storages don't directly improve base
WEIGHT_RESOURCE_BLDG = 3  # Mines, collectors, drills
WEIGHT_TRAP = 12          # Traps help defense but mostly secondary
WEIGHT_WALL = 0           # Excluded entirely from planning


_KEY_DEFENSE_NAMES = {
    "eagle artillery", "inferno tower", "scattershot", "monolith",
    "spell tower", "ricochet cannon", "multi-archer tower", "multi-gear tower",
    "firespitter", "revenge tower", "super wizard tower", "roaster",
    "airbomb", "lava launcher",
}
_STD_DEFENSE_NAMES = {
    "cannon", "archer tower", "mortar", "air defense", "wizard tower",
    "air sweeper", "hidden tesla", "bomb tower", "x-bow",
}
_STORAGE_NAMES = {
    "gold storage", "elixir storage", "dark elixir storage",
}
_RESOURCE_BLDG_NAMES = {
    "gold mine", "elixir collector", "dark elixir drill",
}
_LAB_HOUSE_NAMES = {
    "laboratory", "pet house", "blacksmith", "hero hall",
    "spell factory", "dark spell factory", "workshop",
}
_ARMY_BLDG_NAMES = {
    "army camp", "barracks", "dark barracks", "clan castle",
}
_TRAP_NAMES = {
    "bombs", "spring traps", "giant bomb", "air bomb",
    "seeking air mine", "skeleton trap", "tornado trap", "giga bomb",
    "builder's hut", "builder hut",
}


def _base_name(name: str) -> str:
    if " #" in name:
        return name.split(" #", 1)[0]
    return name


def upgrade_weight(job: UpgradeJob) -> int:
    """Return the strength-value weight for this upgrade. Higher = do earlier."""
    if job.category == Category.WALL:
        return WEIGHT_WALL
    if job.category == Category.TOWN_HALL:
        return WEIGHT_TOWN_HALL
    if job.category == Category.HERO:
        return WEIGHT_HERO
    if job.category == Category.TROOP:
        return WEIGHT_TROOP
    if job.category == Category.SPELL:
        return WEIGHT_SPELL
    if job.category == Category.PET:
        return WEIGHT_PET
    if job.category == Category.BUILDING:
        name = _base_name(job.name).lower()
        if name in _KEY_DEFENSE_NAMES:
            return WEIGHT_KEY_DEFENSE
        if name in _STD_DEFENSE_NAMES:
            return WEIGHT_STD_DEFENSE
        if name in _STORAGE_NAMES:
            return WEIGHT_STORAGE
        if name in _RESOURCE_BLDG_NAMES:
            return WEIGHT_RESOURCE_BLDG
        if name in _LAB_HOUSE_NAMES:
            return WEIGHT_LAB_HOUSE
        if name in _ARMY_BLDG_NAMES:
            return WEIGHT_ARMY_BLDG
        if name in _TRAP_NAMES:
            return WEIGHT_TRAP
        return WEIGHT_STD_DEFENSE  # default for unknown buildings
    return 5


def strength_facet(job: UpgradeJob) -> str:
    """Which 'pillar' of strength this upgrade contributes to (for charting)."""
    if job.category == Category.HERO:
        return "heroes"
    if job.category in (Category.TROOP, Category.SPELL, Category.PET):
        return "army"
    if job.category == Category.WALL:
        return "walls"
    if job.category == Category.TOWN_HALL:
        return "town_hall"
    if job.category == Category.BUILDING:
        name = _base_name(job.name).lower()
        if name in _KEY_DEFENSE_NAMES or name in _STD_DEFENSE_NAMES or name in _TRAP_NAMES:
            return "defense"
        return "infrastructure"
    return "infrastructure"
