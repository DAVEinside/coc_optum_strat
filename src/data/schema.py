"""Data schema for upgrade jobs fed to the scheduler."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class Track(str, Enum):
    BUILDER = "builder"
    LAB = "lab"
    PET_HOUSE = "pet_house"
    FREE = "free"


class Category(str, Enum):
    BUILDING = "building"
    HERO = "hero"
    TROOP = "troop"
    SPELL = "spell"
    PET = "pet"
    WALL = "wall"
    TOWN_HALL = "town_hall"


class Resource(str, Enum):
    GOLD = "gold"
    ELIXIR = "elixir"
    DARK_ELIXIR = "dark_elixir"
    NONE = "none"


class UpgradeJob(BaseModel):
    id: str
    name: str
    category: Category
    from_level: int
    to_level: int
    duration_sec: int = Field(ge=0)
    cost: int = Field(ge=0)
    resource: Resource
    th_required: int = Field(ge=1, le=18)
    prereq_ids: List[str] = Field(default_factory=list)
    track: Track

    @property
    def duration_hours(self) -> float:
        return self.duration_sec / 3600

    @property
    def duration_days(self) -> float:
        return self.duration_sec / 86400
