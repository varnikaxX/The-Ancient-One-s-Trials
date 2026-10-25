"""Stretch: multi-stage pipeline (Coding -> Tech -> HR) with pass/fail routing.

Pure functions only. Verdicts are the strings "PASS" / "FAIL".
"""
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional

from .models import format_ts, parse_ts

ROUND_NAMES = {1: "Coding", 2: "Tech", 3: "HR"}


def eligible_for_next_round(student_history: Iterable[Dict[str, Any]], round_no: int) -> bool:
    """student_history: [{"roundNo": int, "verdict": "PASS"|"FAIL"}].

    Eligible for round_no iff every earlier round was PASSed, no round was
    FAILed (FAIL ends the pipeline) and round_no itself has no verdict yet.
    """
    if round_no not in (1, 2, 3):
        return False
    verdicts = {}
    for h in student_history:
        verdicts[h["roundNo"]] = h["verdict"]
    if "FAIL" in verdicts.values():
        return False
    if round_no in verdicts:
        return False
    return all(verdicts.get(r) == "PASS" for r in range(1, round_no))


def _max_round(rounds_config: Any) -> int:
    if isinstance(rounds_config, dict):
        rounds = rounds_config.get("rounds")
        if isinstance(rounds, list) and rounds:
            return max(1, min(3, len(rounds)))
        nums = [int(k) for k in rounds_config if str(k).isdigit()]
        if nums:
            return max(1, min(3, max(nums)))
    elif isinstance(rounds_config, list) and rounds_config:
        return max(1, min(3, len(rounds_config)))
    return 3


def next_round(results: List[Dict[str, Any]], rounds_config: Any = None) -> Dict[str, Any]:
    """results: [{"studentId", "roundNo", "verdict"}] (all rounds so far).

    Returns {"promoted": [{"studentId", "roundNo"}], "eliminated": [studentId],
             "completed": [studentId]} - each list sorted for determinism.
    promoted.roundNo is the round the student should now be scheduled for.
    """
    last_round = _max_round(rounds_config)
    history: Dict[int, List[Dict[str, Any]]] = {}
    for r in results:
        history.setdefault(r["studentId"], []).append(r)
    promoted, eliminated, completed = [], [], []
    for sid in sorted(history):
        hist = history[sid]
        if any(h["verdict"] == "FAIL" for h in hist):
            eliminated.append(sid)
            continue
        done = max(h["roundNo"] for h in hist)
        if done >= last_round:
            completed.append(sid)
        elif eligible_for_next_round(hist, done + 1):
            promoted.append({"studentId": sid, "roundNo": done + 1})
    return {"promoted": promoted, "eliminated": eliminated, "completed": completed}


def release_time(declared_at: str, delay_minutes: int) -> str:
    """ISO-8601 UTC time at which a declared result becomes visible."""
    return format_ts(parse_ts(declared_at, "declared_at") + timedelta(minutes=delay_minutes))
