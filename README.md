# Clash of Clans — Upgrade Schedule Optimizer

Mathematically optimize the order of upgrades during a Town Hall transition, minimizing time across `m` builders. Uses Google OR-Tools CP-SAT, with an LPT greedy baseline for comparison.

**Primary deliverables:**
- [app.py](app.py) — Streamlit web UI: upload `my_stats.txt`, pick target TH + builders, get a plan
- [notebooks/th15_to_th16.ipynb](notebooks/th15_to_th16.ipynb) — deep dive on one TH transition with all 3 presets
- [notebooks/all_ths.ipynb](notebooks/all_ths.ipynb) — sweep across TH8→TH18, 4 builder counts, 3 presets
- [notebooks/player_demo.ipynb](notebooks/player_demo.ipynb) — reads a real player dump, infers state, plans to target TH

## Run the web app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501. Upload your `my_stats.txt` (or use the bundled sample), pick a target Town Hall, builder count, and optionally income/hours-per-day. The app shows: makespan, Gantt chart, per-builder upgrade list, and a Markdown/CSV export of the plan.

## Problem

`Pm | prec | Cmax` — parallel-machine scheduling with precedence constraints. Three independent machines:

- **Builders** (`m ∈ {1..6}`): buildings, defenses, traps, heroes
- **Laboratory** (1 single machine): troops + spells
- **Pet House** (1 single machine): pets
- **Walls** (free track, instant build, no machine hold)

Precedence: per-entity level chains plus a TH gate (everything at TH-N tier requires TH itself to be at level N).

## Findings

### 1. Lab is the bottleneck

For the `max` preset on most transitions, the schedule is gated by the Laboratory (single machine), not by builders. With 6 builders on TH15→TH16 you reach **337 days** for both LPT and CP-SAT — the same number — because the lab decides.

Marginal value of additional builders for the **max** preset (days saved):

| Transition | m=1→2 | m=2→3 | m=3→6 |
|---|---:|---:|---:|
| TH8→TH9   | 59 | 20 | 5  |
| TH10→TH11 | 124 | 37 | **0** |
| TH13→TH14 | 262 | 82 | **0** |
| TH15→TH16 | 379 | 42 | **0** |
| TH17→TH18 | 634 | **0** | **0** |

The 6th builder (OTTO from Builder Base) is **worthless** for maxing at high TH. Boost the lab with Books of Research / Research Potions instead.

### 2. Selection matters more than builder count

Picking what NOT to upgrade saves more time than adding builders:

| TH transition | max preset (m=6) | balanced (m=6) | rush (m=6) |
|---|---:|---:|---:|
| TH10→TH11 | 87.5 d | 36.8 d | 30.0 d |
| TH13→TH14 | 179.5 d | 79.8 d | 47.0 d |
| TH15→TH16 | 337.0 d | 120.5 d | 72.5 d |
| TH17→TH18 | 721.2 d | 252.5 d | 107.0 d |

Going from "max everything" to "balanced" (heroes maxed, key meta troops, 50% walls) roughly **halves the time**. Rushing further cuts another ~30%.

### 3. CP-SAT vs LPT — gap depends on bottleneck

| Preset | Bottleneck (m=6) | LPT vs CP-SAT gap |
|---|---|---:|
| max | Lab | 0% |
| balanced | Builders | ~25% |
| rush | Builders | ~30% |

When you're builder-bound, the scheduling math really matters. When you're lab-bound, any ordering of the builder track gives the same total time because the lab decides.

### 4. Cumulative path TH8 → TH18 maxed (6 builders, CP-SAT)

Rough totals from the all-TH notebook:

| Preset | Cumulative days TH8→TH18 |
|---|---:|
| max | ~2400 d (~6.5 years) |
| balanced | ~960 d (~2.6 years) |
| rush | ~560 d (~1.5 years) |

## Project structure

```
app.py                    # Streamlit web app
notebooks/
  th15_to_th16.ipynb      # one-transition deep dive
  all_ths.ipynb           # TH8 -> TH18 sweep with all presets
  player_demo.ipynb       # plan from a real player's my_stats.txt
  my_stats.txt            # sample Supercell player data
src/
  data/
    schema.py             # pydantic UpgradeJob
    xlsx_parser.py        # parse structs_data.xlsx into per-level rows
    loaders.py            # JSON + xlsx -> UpgradeJob list
    player.py             # parse Supercell my_stats.txt -> PlayerState
    player_loader.py      # UpgradeJobs from PlayerState to target TH
  optim/
    cpsat.py              # OR-Tools CP-SAT solver (LPT warm-start, resource-aware)
    lpt.py                # LPT greedy baseline
    selector.py           # YAML profile -> filtered job set
    resources.py          # Income-rate constraints + default rates per TH
    verify.py             # post-solve assertions
  viz/
    gantt.py              # Plotly Gantt + bar charts
    schedule_list.py      # human-readable "do X then Y" output
config/
  selection_max.yaml      # upgrade everything
  selection_balanced.yaml # heroes max, selected troops, 50% walls
  selection_rush.yaml     # heroes + critical defenses only
data_repo/
  clash-of-clans-data/    # existing JSON parser (troops/heroes/spells/pets)
  structs_data.xlsx       # wiki-sourced building upgrade data
  manual/                 # legacy hand-curated CSV (no longer used)
requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
```

Open either notebook in Jupyter. Both are already executed with results visible.

To re-run:
```bash
python -m nbconvert --to notebook --execute notebooks/th15_to_th16.ipynb \
  --output th15_to_th16.ipynb --ExecutePreprocessor.timeout=600
python -m nbconvert --to notebook --execute notebooks/all_ths.ipynb \
  --output all_ths.ipynb --ExecutePreprocessor.timeout=1200
```

## Data sources

- **Buildings**: [`data_repo/structs_data.xlsx`](data_repo/structs_data.xlsx) — wiki-sourced upgrade tables for all 50 home-village structures. Parser at [`src/data/xlsx_parser.py`](src/data/xlsx_parser.py) reads cost, time, TH-required per level, plus a hardcoded per-TH instance-count table.
- **Troops/heroes/spells/pets**: existing JSON repo at `data_repo/clash-of-clans-data/`. Per-level cost/time arrays + TH-level gates.
- **Player initial state** (planned): Supercell's player API — see [`notebooks/my_stats.txt`](notebooks/my_stats.txt) for an example response.

## Selection profiles

Edit [`config/selection_*.yaml`](config/) to change which entities are targets. Each profile has the same fields (heroes, defenses, troops, spells, pets, walls, town_hall) with per-bucket rules (all_max / none / whitelist).

## Roadmap

- [x] TH15→TH16 deep dive with CP-SAT + LPT, all 3 presets
- [x] Wiki data integration via xlsx; all-TH sweep
- [x] Player import — parse `my_stats.txt` to set initial entity levels
- [x] Income-rate resource model (optional): hourly income + hours/day → flow constraint
- [x] Streamlit web app
- [ ] Future (if useful): hero equipment, Builder Base, league/event resources

### Income model (when enabled)

[`src/optim/resources.py`](src/optim/resources.py) — flow-only model:
- User inputs gold+elixir per active hour (default 4M/h) and hours played per day (default 6).
- Effective rate = active_rate × hours / 24.
- Constraint: cumulative consumption by time t ≤ initial stockpile + effective_rate × t (per resource, OR-Tools reservoir).
- Storage caps not enforced — they cause infeasibility cycles when income > cap, and don't change the headline answer for multi-year plans (where the Lab dominates anyway).
- Smart pruning: if a resource has > 30% headroom over the LPT bound, the constraint is skipped.

## Verification

Every schedule is checked by [`src/optim/verify.py`](src/optim/verify.py):

1. Every job scheduled exactly once
2. Each `end − start == duration`
3. Precedence: `end(parent) ≤ start(child)` for every edge
4. No builder runs two jobs simultaneously
5. Lab and Pet House never overlap (single machines)
6. Sweep-line: at most `m` builder jobs active at any instant
7. Makespan ≥ lower bound (max of per-track work / capacity)

## Limitations

- Unlimited resources assumption (Phase 3 will address)
- Building instance counts are hardcoded by TH level (in [`src/data/xlsx_parser.py`](src/data/xlsx_parser.py) — see `INSTANCE_COUNT` dict). Update if Supercell changes layouts.
- Hero equipment (Blacksmith) and Builder Base are out of scope
- Selection profiles encode personal judgment; future v2 could optimize selection given an army-strength utility function
