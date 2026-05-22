"""Finite-resource (income only) constraints for the CP-SAT scheduler.

Simple model:
- Each resource has an `initial` stockpile and a per-hour income while playing.
- `active_hours_per_day` averages the income over 24h (e.g. 6h/day at 4M/h => 1M/h average).
- For each job consuming cost C of resource R at time t, we require that cumulative
  consumption by t <= initial[R] + avg_rate[R] * t.
- Storage caps are NOT enforced — they cause infeasibility cycles in models with large
  income relative to cap, and at multi-year horizons they don't move the headline number.

We use OR-Tools `AddReservoirConstraint` with weekly refill discretization. The smart
binding-check skips the constraint entirely for resources with comfortable headroom.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ortools.sat.python import cp_model

from src.data.schema import Resource, UpgradeJob


DAY = 86400
HOUR = 3600


# --- Default farming rates (rough community averages for active players) ---
DEFAULT_RATES_BY_TH: Dict[int, Dict[str, int]] = {
    8:  {"gold": 250_000, "elixir": 250_000, "dark_elixir": 1_000},
    9:  {"gold": 400_000, "elixir": 400_000, "dark_elixir": 2_000},
    10: {"gold": 600_000, "elixir": 600_000, "dark_elixir": 3_000},
    11: {"gold": 800_000, "elixir": 800_000, "dark_elixir": 4_500},
    12: {"gold": 1_200_000, "elixir": 1_200_000, "dark_elixir": 6_000},
    13: {"gold": 1_800_000, "elixir": 1_800_000, "dark_elixir": 9_000},
    14: {"gold": 2_500_000, "elixir": 2_500_000, "dark_elixir": 12_000},
    15: {"gold": 3_000_000, "elixir": 3_000_000, "dark_elixir": 15_000},
    16: {"gold": 3_500_000, "elixir": 3_500_000, "dark_elixir": 18_000},
    17: {"gold": 4_000_000, "elixir": 4_000_000, "dark_elixir": 20_000},
    18: {"gold": 5_000_000, "elixir": 5_000_000, "dark_elixir": 25_000},
}


@dataclass
class ResourceBudget:
    """Income-only resource model.

    - `initial`: starting stockpile per resource (gold/elixir/dark_elixir)
    - `rate_per_hour_active`: income per hour WHILE actively playing
    - `active_hours_per_day`: hours/day spent playing (default 6)
    """
    initial: Dict[str, int] = field(default_factory=dict)
    rate_per_hour_active: Dict[str, int] = field(default_factory=dict)
    active_hours_per_day: float = 6.0

    @property
    def rate_per_hour(self) -> Dict[str, int]:
        """Time-averaged income rate per hour (income spread across 24h)."""
        return {k: int(v * self.active_hours_per_day / 24)
                for k, v in self.rate_per_hour_active.items()}

    @classmethod
    def from_th(cls, th: int, initial: Optional[Dict[str, int]] = None,
                active_hours_per_day: float = 6.0) -> "ResourceBudget":
        rates = DEFAULT_RATES_BY_TH.get(th, DEFAULT_RATES_BY_TH[16])
        return cls(
            initial=initial or {r: 0 for r in rates},
            rate_per_hour_active=dict(rates),
            active_hours_per_day=active_hours_per_day,
        )

    @classmethod
    def from_uniform_rate(cls, rate_per_hour_active: int,
                          active_hours_per_day: float = 6.0,
                          initial: Optional[Dict[str, int]] = None,
                          de_factor: float = 0.005) -> "ResourceBudget":
        """All resources at a uniform active rate; DE scaled down by `de_factor`.

        Default de_factor=0.5% reflects DE's much lower farm rate vs gold/elixir.
        """
        rates = {
            "gold": rate_per_hour_active,
            "elixir": rate_per_hour_active,
            "dark_elixir": int(rate_per_hour_active * de_factor),
        }
        return cls(
            initial=initial or {k: 0 for k in rates},
            rate_per_hour_active=rates,
            active_hours_per_day=active_hours_per_day,
        )


def _is_resource_potentially_binding(
    jobs: List[UpgradeJob], r_enum, initial: int, rate_per_hour: int, lpt_makespan_sec: int,
) -> bool:
    """Skip the (expensive) constraint when a resource has comfortable headroom."""
    consuming = [j for j in jobs if j.cost > 0 and j.resource == r_enum]
    if not consuming:
        return False
    total_demand = sum(j.cost for j in consuming)
    available = initial + rate_per_hour * (lpt_makespan_sec / 3600)
    return total_demand > available * 0.7


def add_resource_constraints(
    model: cp_model.CpModel,
    jobs: List[UpgradeJob],
    start_by_id: Dict[str, cp_model.IntVar],
    budget: ResourceBudget,
    horizon_sec: int,
    refill_period_days: int = 7,
    lpt_makespan_sec: Optional[int] = None,
) -> None:
    """Add per-resource reservoir constraints (income only, no upper cap)."""
    period_sec = refill_period_days * DAY
    horizon_periods = int(horizon_sec / period_sec) + 2

    for r_name in ("gold", "elixir", "dark_elixir"):
        r_enum = {"gold": Resource.GOLD, "elixir": Resource.ELIXIR,
                  "dark_elixir": Resource.DARK_ELIXIR}[r_name]
        rate = budget.rate_per_hour.get(r_name, 0)
        initial = budget.initial.get(r_name, 0)

        if lpt_makespan_sec is not None and not _is_resource_potentially_binding(
            jobs, r_enum, initial, rate, lpt_makespan_sec
        ):
            continue

        times: List = []
        deltas: List[int] = []

        if rate > 0:
            per_period = rate * 24 * refill_period_days
            for d in range(1, horizon_periods + 1):
                times.append(d * period_sec)
                deltas.append(per_period)

        for j in jobs:
            if j.cost > 0 and j.resource == r_enum:
                times.append(start_by_id[j.id])
                deltas.append(-int(j.cost))

        if not times:
            continue

        # min_level = -initial (so absolute stock = initial + level >= 0).
        # No upper cap (effective infinity).
        model.AddReservoirConstraint(times, deltas, -initial, 10**14)
