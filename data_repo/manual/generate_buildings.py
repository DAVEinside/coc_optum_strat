"""Generates `buildings_th15_to_th16.csv` from curated TH15->TH16 upgrade data.

Numbers are best-effort from common community references (Clash of Clans wiki, 2024-2026).
Edit this file to refine — the rest of the pipeline reads the generated CSV.

Each row in the output CSV represents ONE upgrade for ONE instance of a building.
For buildings with multiple instances (e.g. 7 cannons), we emit one row per instance per
level transition. The scheduler then sees them as independent jobs.

For TH15->TH16: walls are "free" track (no builder), all other buildings use a builder.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Each entry: (name, instance_count, [ (from_level, to_level, gold_cost, time_sec, th_req, resource), ... ])
# - 'gold_cost' column is the cost in the listed resource (gold/elixir).
# - time in seconds.

DAY = 86400
HOUR = 3600

# ------- Helper: build a (from->to) chain for a building with same time/cost step -------
def chain(name, instances, lvl_data, th_req, resource="gold", track="builder", category="building"):
    """lvl_data: list of (from, to, cost, time_sec) tuples."""
    rows = []
    for inst in range(1, instances + 1):
        for (f, t, c, dur) in lvl_data:
            rows.append({
                "name": f"{name} #{inst}" if instances > 1 else name,
                "category": category,
                "from_level": f,
                "to_level": t,
                "cost": c,
                "duration_sec": dur,
                "resource": resource,
                "th_required": th_req,
                "track": track,
            })
    return rows


BUILDINGS = []

# --- Town Hall itself: TH15 -> TH16 ---
# Known: TH16 upgrade is ~18d, 20M gold. (Released Dec 2023, modern values.)
BUILDINGS += chain("Town Hall", 1, [(15, 16, 20_000_000, 18 * DAY)],
                   th_req=15, resource="gold", category="town_hall")

# --- DEFENSES (TH15 max -> TH16 max) ---
# Cannon: TH15 max=20, TH16 max=22. 7 instances.
BUILDINGS += chain("Cannon", 7, [
    (20, 21, 19_000_000, 14 * DAY + 12 * HOUR),
    (21, 22, 20_000_000, 15 * DAY),
], th_req=16)

# Archer Tower: TH15 max=21, TH16 max=23. 8 instances.
BUILDINGS += chain("Archer Tower", 8, [
    (21, 22, 19_500_000, 14 * DAY + 12 * HOUR),
    (22, 23, 20_500_000, 15 * DAY),
], th_req=16)

# Mortar: TH15 max=15, TH16 max=16. 4 instances.
BUILDINGS += chain("Mortar", 4, [
    (15, 16, 21_000_000, 15 * DAY + 12 * HOUR),
], th_req=16)

# Air Defense: TH15 max=13, TH16 max=14. 4 instances.
BUILDINGS += chain("Air Defense", 4, [
    (13, 14, 22_000_000, 16 * DAY),
], th_req=16)

# Wizard Tower: TH15 max=15, TH16 max=16. 5 instances.
BUILDINGS += chain("Wizard Tower", 5, [
    (15, 16, 21_500_000, 15 * DAY + 12 * HOUR),
], th_req=16)

# Air Sweeper: TH15 max=7, TH16 max=8. 2 instances.
BUILDINGS += chain("Air Sweeper", 2, [
    (7, 8, 18_000_000, 14 * DAY),
], th_req=16)

# Hidden Tesla: TH15 max=13, TH16 max=14. 7 instances.
BUILDINGS += chain("Hidden Tesla", 7, [
    (13, 14, 21_000_000, 15 * DAY),
], th_req=16)

# Bomb Tower: TH15 max=11, TH16 max=12. 2 instances.
BUILDINGS += chain("Bomb Tower", 2, [
    (11, 12, 20_000_000, 15 * DAY),
], th_req=16)

# X-Bow: TH15 max=10, TH16 max=11. 4 instances.
BUILDINGS += chain("X-Bow", 4, [
    (10, 11, 22_000_000, 16 * DAY),
], th_req=16)

# Inferno Tower: TH15 max=10, TH16 max=11. 3 instances.
BUILDINGS += chain("Inferno Tower", 3, [
    (10, 11, 22_500_000, 16 * DAY + 12 * HOUR),
], th_req=16)

# Eagle Artillery: TH15 max=6, TH16 max=7. 1 instance.
BUILDINGS += chain("Eagle Artillery", 1, [
    (6, 7, 22_500_000, 17 * DAY),
], th_req=16)

# Scattershot: TH15 max=4, TH16 max=5. 4 instances.
BUILDINGS += chain("Scattershot", 4, [
    (4, 5, 22_500_000, 17 * DAY),
], th_req=16)

# Spell Tower: TH15 max=2, TH16 max=3. 2 instances.
BUILDINGS += chain("Spell Tower", 2, [
    (2, 3, 21_000_000, 15 * DAY),
], th_req=16)

# Monolith: TH15 max=2, TH16 max=3. 1 instance.
BUILDINGS += chain("Monolith", 1, [
    (2, 3, 22_500_000, 17 * DAY),
], th_req=16)

# Ricochet Cannon: NEW at TH16 (unlocks fresh). Build cost only.
# Assume needs to be built from scratch to max (~level 3 at TH16).
BUILDINGS += chain("Ricochet Cannon", 2, [
    (0, 1, 18_000_000, 12 * DAY),
    (1, 2, 19_000_000, 13 * DAY),
    (2, 3, 20_000_000, 14 * DAY),
], th_req=16)

# Multi-Archer Tower: TH16 NEW. 1 instance.
BUILDINGS += chain("Multi-Archer Tower", 1, [
    (0, 1, 18_000_000, 12 * DAY),
    (1, 2, 19_000_000, 13 * DAY),
    (2, 3, 20_000_000, 14 * DAY),
], th_req=16)

# Multi-Gear Tower: TH16 NEW. 1 instance.
BUILDINGS += chain("Multi-Gear Tower", 1, [
    (0, 1, 18_000_000, 12 * DAY),
    (1, 2, 19_000_000, 13 * DAY),
    (2, 3, 20_000_000, 14 * DAY),
], th_req=16)

# --- TRAPS (instant, but use a builder briefly? — we model as builder track w/ ~1 hr cost.) ---
# Skipping detailed traps for v1; their time is negligible relative to defenses.

# --- HERO HALLS / HERO ALTARS: Hero upgrades themselves are in the JSON troop data already.
# But the *altar* buildings (BK Altar, etc.) may need a level-up at the TH transition.
# We skip these for v1; they're usually instant or quick.

# --- ARMY BUILDINGS ---
# Laboratory: TH15 max=13, TH16 max=14. 1 instance.
BUILDINGS += chain("Laboratory", 1, [(13, 14, 21_000_000, 15 * DAY)],
                   th_req=16, resource="elixir")

# Spell Factory: TH15 max=7, TH16 max=8. 1 instance.
BUILDINGS += chain("Spell Factory", 1, [(7, 8, 17_500_000, 12 * DAY)],
                   th_req=16, resource="elixir")

# Dark Spell Factory: TH15 max=6, TH16 max=7. 1 instance.
BUILDINGS += chain("Dark Spell Factory", 1, [(6, 7, 17_000_000, 11 * DAY)],
                   th_req=16, resource="elixir")

# Barracks: TH15 max=17, TH16 max=18. 4 instances.
BUILDINGS += chain("Barracks", 4, [(17, 18, 21_000_000, 15 * DAY)],
                   th_req=16, resource="elixir")

# Dark Barracks: TH15 max=11, TH16 max=12. 2 instances.
BUILDINGS += chain("Dark Barracks", 2, [(11, 12, 21_000_000, 15 * DAY)],
                   th_req=16, resource="elixir")

# Army Camp: TH15 max=12, TH16 max=13. 4 instances.
BUILDINGS += chain("Army Camp", 4, [(12, 13, 21_000_000, 15 * DAY)],
                   th_req=16, resource="elixir")

# Pet House: TH15 max=10, TH16 max=11. 1 instance.
BUILDINGS += chain("Pet House", 1, [(10, 11, 22_000_000, 16 * DAY)],
                   th_req=16, resource="elixir")

# Clan Castle: TH15 max=11, TH16 max=12. 1 instance.
BUILDINGS += chain("Clan Castle", 1, [(11, 12, 21_000_000, 15 * DAY)],
                   th_req=16, resource="gold")

# --- RESOURCE BUILDINGS ---
# Gold Storage: TH15 max=16, TH16 max=17. 4 instances.
BUILDINGS += chain("Gold Storage", 4, [(16, 17, 22_000_000, 16 * DAY)],
                   th_req=16, resource="elixir")

# Elixir Storage: TH15 max=16, TH16 max=17. 4 instances.
BUILDINGS += chain("Elixir Storage", 4, [(16, 17, 22_000_000, 16 * DAY)],
                   th_req=16, resource="gold")

# Dark Elixir Storage: TH15 max=11, TH16 max=12. 1 instance.
BUILDINGS += chain("Dark Elixir Storage", 1, [(11, 12, 22_000_000, 16 * DAY)],
                   th_req=16, resource="gold")

# Gold Mine: TH15 max=15, TH16 max=16. 7 instances.
BUILDINGS += chain("Gold Mine", 7, [(15, 16, 15_000_000, 10 * DAY)],
                   th_req=16, resource="elixir")

# Elixir Collector: TH15 max=15, TH16 max=16. 7 instances.
BUILDINGS += chain("Elixir Collector", 7, [(15, 16, 15_000_000, 10 * DAY)],
                   th_req=16, resource="gold")

# Dark Elixir Drill: TH15 max=10, TH16 max=11. 3 instances.
BUILDINGS += chain("Dark Elixir Drill", 3, [(10, 11, 18_000_000, 14 * DAY)],
                   th_req=16, resource="gold")

# Builder's Hut: TH15 max=4 (defensive form), TH16 max=5. 5 instances.
BUILDINGS += chain("Builder's Hut", 5, [(4, 5, 18_000_000, 14 * DAY)],
                   th_req=16, resource="gold")

# --- WALLS (free track — instant build but resource heavy) ---
# TH15 max wall level = 16, TH16 max = 17.
# Wall count at TH15+ is ~325. For demo, we instantiate a representative subset.
# Each wall upgrade is instant (1 second model), gold or elixir cost.
WALL_COUNT_DEMO = 50  # demo subset of walls; full 325 would inflate row count without affecting makespan
BUILDINGS += chain("Wall", WALL_COUNT_DEMO, [
    (16, 17, 7_000_000, 1),
], th_req=16, resource="gold", track="free", category="wall")


def main():
    out_path = Path(__file__).parent / "buildings_th15_to_th16.csv"
    fieldnames = ["name", "category", "from_level", "to_level", "duration_sec", "cost", "resource", "th_required", "track"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in BUILDINGS:
            w.writerow({k: row[k] for k in fieldnames})
    print(f"Wrote {len(BUILDINGS)} rows to {out_path}")


if __name__ == "__main__":
    main()
