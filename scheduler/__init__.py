"""Scheduling / logic engine for "The Ancient One's Trials" (Part B).

Pure Python (OR-Tools CP-SAT). No DB, HTTP or Redis imports.
Backend usage:  from scheduler import solve_batch, reschedule
"""
from .solve_batch import solve_batch
from .reschedule import reschedule
from .panel import build_panel_slots, replace_panelist
from .pipeline import eligible_for_next_round, next_round, release_time
from .ranking import aggregate_ranking

__all__ = [
    "solve_batch", "reschedule",
    "build_panel_slots", "replace_panelist",
    "next_round", "eligible_for_next_round", "release_time",
    "aggregate_ranking",
]
