# Clash of Clans — Upgrade Optimizer

A Streamlit web app that takes your Clash of Clans player state and produces an ordered upgrade plan that **prioritizes high-value progress first** — heroes, key defenses, and troops before storages and resource buildings — while respecting builder/Lab/Pet House parallelism.

Built on Google OR-Tools CP-SAT with a weighted-completion-time objective.

## Live use

1. **In Clash of Clans** → Settings → More Settings → press *Copy ID* / share-player-data.
2. **Open the app** (locally `streamlit run app.py`, or your deployed instance).
3. Paste your data into the sidebar, pick a target Town Hall, and click **Compute upgrade plan**.

The app shows:
- **Time to maxed Town Hall** and bottleneck track
- **Ordered "do these first" list** with a slider to show 10 → all upgrades
- **Per-machine tabs**: Laboratory, Pet House, Builder 1-6 separately
- **Markdown / CSV download** of the full plan

## How it works

The optimizer schedules every upgrade between your current state and target-TH max across three independent tracks:

- **Builders** (1-6, you choose): buildings, defenses, traps, heroes
- **Laboratory** (single researcher): troops + spells
- **Pet House** (single trainer): pets

Each upgrade has a strength weight. Heroes and key defenses score highest, storages and resource buildings lowest. The solver minimizes `Σ weight × completion_time` — meaning high-value upgrades land early in the schedule even though everything eventually maxes.

Walls are excluded (they upgrade instantly and are usually handled manually).

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501.

## Deploy

This is a pure Python + Streamlit project. To deploy on **Streamlit Community Cloud**:

1. Push to a public GitHub repo (the `data/` and `sample_player.txt` files are required at runtime — don't `.gitignore` them).
2. Connect the repo at https://share.streamlit.io and pick `app.py` as the entry point.
3. Streamlit auto-installs from `requirements.txt`.

That's it. The app has no secrets, no external services, no database.

## Project structure

```
app.py                       # Streamlit entry point
sample_player.txt            # Sample Supercell player payload (TH17/18 rushed)
data/
  troops.json                # Wiki-sourced troop/hero/spell/pet upgrade tables
  buildings.xlsx             # Wiki-sourced building/trap/wall upgrade tables
src/
  data/
    schema.py                # pydantic UpgradeJob model
    player.py                # parse Supercell payload → PlayerState
    player_loader.py         # PlayerState + target TH → list[UpgradeJob]
    xlsx_parser.py           # parse buildings.xlsx
    loaders.py               # TH-gate precedence helper
  optim/
    cpsat.py                 # OR-Tools CP-SAT solver (weighted-CT objective + LPT fallback)
    lpt.py                   # Greedy priority-list scheduler (used as fallback / warm-start)
    resources.py             # Optional income-rate constraint
    strength.py              # Strength weights per upgrade
    verify.py                # Post-solve precedence + no-overlap asserts
  viz/
    schedule_list.py         # DataFrame + Markdown views of a Schedule
requirements.txt
```

## Caveats

- **Building ID mapping** for the Supercell payload is best-effort. Hero/troop/spell/pet levels parse reliably from in-game IDs; building names use a community-derived table that may not match Supercell's internal IDs 1:1. The default behavior assumes "all buildings at current-TH max" rather than reading individual building levels.
- **Storage caps** are not enforced. Income (optional) acts as a flow constraint only.
- **Town Hall inference** uses your max hero level. If wrong, override it in the sidebar.
- **Hero equipment** and **Builder Base** are out of scope.

## Tech

- [Streamlit](https://streamlit.io) — web UI
- [Google OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver) — constraint scheduler
- [pydantic](https://docs.pydantic.dev) — typed job records
- [pandas](https://pandas.pydata.org) — data manipulation
- [openpyxl](https://openpyxl.readthedocs.io) — building data spreadsheet

## License

This is a hobbyist tool. Clash of Clans is a trademark of Supercell — this project is not affiliated with or endorsed by Supercell.
