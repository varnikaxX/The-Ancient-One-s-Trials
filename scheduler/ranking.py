"""Stretch: blinded evaluation aggregation.

Each interviewer's scores are z-score normalised per criterion so harsh and
lenient graders cancel out; then averaged per candidate. Interviewers who gave
a single score (or identical scores) contribute 0 for that criterion.
Ties are broken by studentId so the output is fully deterministic.
"""
import math
from typing import Any, Dict, List, Optional


def _eval_criteria(ev: Dict[str, Any]) -> Dict[str, float]:
    crit = ev.get("criteria")
    if isinstance(crit, dict) and crit:
        return {str(k): float(v) for k, v in crit.items()}
    if ev.get("total") is not None:
        return {"total": float(ev["total"])}
    return {}


def aggregate_ranking(evaluations: List[Dict[str, Any]],
                      weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """evaluations: [{"studentId", "interviewerId", "criteria": {name: score}}].
    weights: optional {criterion: weight} (default 1). Returns
    [{"studentId", "perCriterion": {c: z}, "total": float, "rank": int}] sorted by rank."""
    weights = weights or {}
    parsed = [(e["studentId"], e["interviewerId"], _eval_criteria(e)) for e in evaluations]

    # mean / std per (interviewer, criterion)
    samples: Dict[tuple, List[float]] = {}
    for _, iid, crit in parsed:
        for c, v in crit.items():
            samples.setdefault((iid, c), []).append(v)
    stats = {}
    for key, vals in samples.items():
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[key] = (mean, math.sqrt(var))

    per_student: Dict[Any, Dict[str, List[float]]] = {}
    for sid, iid, crit in parsed:
        for c, v in crit.items():
            mean, std = stats[(iid, c)]
            z = (v - mean) / std if std > 1e-9 else 0.0
            per_student.setdefault(sid, {}).setdefault(c, []).append(z)

    rows = []
    for sid, crits in per_student.items():
        per = {c: sum(zs) / len(zs) for c, zs in crits.items()}
        wsum = sum(weights.get(c, 1.0) for c in per)
        total = sum(weights.get(c, 1.0) * z for c, z in per.items()) / wsum if wsum else 0.0
        rows.append({"studentId": sid,
                     "perCriterion": {c: round(per[c], 6) for c in sorted(per)},
                     "total": round(total, 6)})
    rows.sort(key=lambda r: (-r["total"], r["studentId"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows
