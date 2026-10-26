"""STRETCH: blinded evaluations + aggregated ranking.

Blinding: interviewers can only POST their own evaluation; there is no endpoint that returns another
interviewer's scores (the POST response contains only the caller's own numbers). Only the coordinator
sees the aggregate, via scheduler.ranking.aggregate_ranking when the package has it, otherwise the
built-in z-score fallback below (same output shape)."""
import math
from collections import defaultdict
from statistics import mean, pstdev

from app import db
from app.errors import ApiError


def submit_evaluation(interview_id: int, interviewer_id: int, criteria: dict) -> dict:
    if not criteria:
        raise ApiError("VALIDATION", "criteria must not be empty")
    if any((not isinstance(v, (int, float))) or v < 0 or v > 10 for v in criteria.values()):
        raise ApiError("VALIDATION", "Each criterion score must be between 0 and 10")
    total = round(mean(criteria.values()), 3)
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM interview_panel WHERE interview_id = %s AND interviewer_id = %s",
                            (interview_id, interviewer_id)).fetchone():
            raise ApiError("FORBIDDEN", "You are not on this interview")
        row = conn.execute(
            """INSERT INTO evaluations (interview_id, interviewer_id, criteria, total) VALUES (%s, %s, %s, %s)
               ON CONFLICT (interview_id, interviewer_id)
               DO UPDATE SET criteria = EXCLUDED.criteria, total = EXCLUDED.total, submitted_at = now()
               RETURNING id, submitted_at""", (interview_id, interviewer_id, db.jsonb(criteria), total)).fetchone()
    return {"id": row["id"], "interviewId": interview_id, "criteria": criteria, "total": total,
            "submittedAt": db.iso(row["submitted_at"])}


def _fallback_ranking(evaluations: list) -> list:
    """Per-interviewer z-score normalisation (cancels harsh/lenient graders), average per candidate."""
    by_iv = defaultdict(list)
    for e in evaluations:
        by_iv[e["interviewerId"]].append(e["total"])
    stats = {iv: (mean(v), pstdev(v) or 1.0) for iv, v in by_iv.items()}
    per_student = defaultdict(lambda: {"totals": [], "crit": defaultdict(list)})
    for e in evaluations:
        mu, sd = stats[e["interviewerId"]]
        per_student[e["studentId"]]["totals"].append((e["total"] - mu) / sd)
        for k, v in (e["criteria"] or {}).items():
            per_student[e["studentId"]]["crit"][k].append(v)
    rows = [{"studentId": sid, "perCriterion": {k: round(mean(v), 3) for k, v in d["crit"].items()},
             "total": round(mean(d["totals"]), 4)} for sid, d in per_student.items()]
    rows.sort(key=lambda r: (-r["total"], r["studentId"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def ranking_for_company(company_id: int) -> list:
    with db.transaction() as conn:
        rows = conn.execute(
            """SELECT e.interview_id, e.interviewer_id, i.student_id, e.criteria, e.total, su.name
               FROM evaluations e JOIN interviews i ON i.id = e.interview_id JOIN users su ON su.id = i.student_id
               WHERE i.company_id = %s ORDER BY e.id""", (company_id,)).fetchall()
    evaluations = [{"interviewId": r["interview_id"], "interviewerId": r["interviewer_id"], "studentId": r["student_id"],
                    "criteria": {k: float(v) for k, v in (r["criteria"] or {}).items()}, "total": float(r["total"])} for r in rows]
    names = {r["student_id"]: r["name"] for r in rows}
    ranking = None
    try:
        from scheduler.ranking import aggregate_ranking
        ranking = aggregate_ranking(evaluations, {})
    except Exception:  # noqa: BLE001
        ranking = None
    if not ranking or any(math.isnan(r.get("total", 0)) for r in ranking):
        ranking = _fallback_ranking(evaluations)
    return [dict(r, studentName=names.get(r["studentId"], "")) for r in ranking]
