"""Plotly Gantt charts for builder/lab/pet-house schedules."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.data.schema import Track
from src.optim.lpt import Schedule


_CATEGORY_COLORS = {
    "town_hall": "#222222",
    "hero": "#d62728",
    "building": "#1f77b4",
    "wall": "#7f7f7f",
    "troop": "#2ca02c",
    "spell": "#9467bd",
    "pet": "#ff7f0e",
}


def schedule_to_dataframe(schedule: Schedule, t0: datetime = datetime(2026, 1, 1)) -> pd.DataFrame:
    """Convert a Schedule into a DataFrame with absolute timestamps for plotting."""
    rows = []
    for s in schedule.items:
        track = s.job.track.value
        cat = s.job.category.value
        if track == "builder":
            row_label = f"Builder {s.machine + 1}"
        elif track == "lab":
            row_label = "Laboratory"
        elif track == "pet_house":
            row_label = "Pet House"
        else:
            row_label = "Walls (free)"
        rows.append({
            "Task": s.job.name,
            "JobID": s.job.id,
            "Category": cat,
            "Track": track,
            "Row": row_label,
            "Machine": s.machine,
            "StartSec": s.start_sec,
            "EndSec": s.end_sec,
            "DurationDays": (s.end_sec - s.start_sec) / 86400,
            "Start": t0 + timedelta(seconds=s.start_sec),
            "End": t0 + timedelta(seconds=s.end_sec),
            "FromLevel": s.job.from_level,
            "ToLevel": s.job.to_level,
        })
    return pd.DataFrame(rows)


def make_gantt(schedule: Schedule, title: str = "Upgrade schedule",
               include_walls: bool = False) -> go.Figure:
    df = schedule_to_dataframe(schedule)
    if not include_walls:
        df = df[df["Track"] != "free"]

    # Order rows: Builders first (1..N), then Lab, then Pet House
    row_order = []
    builders = sorted([r for r in df["Row"].unique() if r.startswith("Builder")],
                      key=lambda x: int(x.split()[-1]))
    row_order += builders
    if "Laboratory" in df["Row"].values:
        row_order.append("Laboratory")
    if "Pet House" in df["Row"].values:
        row_order.append("Pet House")
    if include_walls and "Walls (free)" in df["Row"].values:
        row_order.append("Walls (free)")

    fig = px.timeline(
        df, x_start="Start", x_end="End", y="Row", color="Category",
        color_discrete_map=_CATEGORY_COLORS,
        hover_data=["Task", "FromLevel", "ToLevel", "DurationDays"],
        title=title,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=row_order[::-1])
    fig.update_layout(height=max(400, 60 * len(row_order)), bargap=0.15)
    return fig


def builder_comparison_bar(makespans: dict, title: str = "Makespan vs builder count") -> go.Figure:
    """makespans: {m: makespan_days}"""
    fig = go.Figure()
    fig.add_bar(
        x=[str(m) for m in sorted(makespans)],
        y=[makespans[m] for m in sorted(makespans)],
        text=[f"{makespans[m]:.0f}d" for m in sorted(makespans)],
        textposition="outside",
    )
    fig.update_layout(
        title=title,
        xaxis_title="Number of builders",
        yaxis_title="Makespan (days)",
        height=400,
    )
    return fig


def preset_comparison_bar(results: dict, title: str = "Preset comparison") -> go.Figure:
    """results: {preset_name: {m: makespan_days}}"""
    fig = go.Figure()
    presets = list(results.keys())
    ms = sorted({m for r in results.values() for m in r})
    for preset in presets:
        fig.add_bar(
            x=[str(m) for m in ms],
            y=[results[preset].get(m) for m in ms],
            name=preset,
        )
    fig.update_layout(
        title=title,
        xaxis_title="Builders",
        yaxis_title="Makespan (days)",
        barmode="group",
        height=450,
    )
    return fig
