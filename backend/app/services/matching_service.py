"""Batch matching. The API only ENQUEUES (run_matching); the solver runs inside the Celery worker
(solve_round -> called by workers.tasks.solve_round_task and nowhere else)."""
import logging
from datetime import datetime

from app import db
from app.config import settings
from app.errors import ApiError
from app.services import cache, notification_service as notify
from app.services.views import ROUND_SKILL

log = logging.getLogger("trials.matching")
DEFAULT_WEIGHTS = {"rank1": 100, "rank2": 60, "rank3": 30, "unmatchedPenalty": 1000}


def get_solver():
    """Single switch point: USE_STUB_SOLVER=true -> greedy stub, false -> Varnika's scheduler package."""
    if settings.use_stub_solver:
        from app.services import solver_stub as mod
        return mod.solve_batch, mod.reschedule
    from scheduler import solve_batch, reschedule  # noqa: WPS433  (repo-root package)
    return solve_batch, reschedule


def run_matching(round_no: int) -> dict:
    """POST /coordinator/matching/run -> {jobId}. Cheap: just enqueue."""
    if round_no not in ROUND_SKILL:
        raise ApiError("VALIDATION", "roundNo must be 1, 2 or 3")
    from workers.tasks import solve_round_task
    try:
        job = solve_round_task.delay(round_no)
    except Exception as exc:  # noqa: BLE001
        log.error("enqueue failed: %s", exc)
        raise ApiError("VALIDATION", "Matching queue is unavailable right now, please retry shortly")
    return {"jobId": job.id}


# ───────────────────────── worker side ─────────────────────────
def _release_old_drafts(conn, round_no: int):
    """New batch run supersedes unapproved drafts: free their held slots, reset their preferences."""
    for d in conn.execute("SELECT id FROM schedule_drafts WHERE round_no = %s AND status = 'DRAFT' FOR UPDATE",
                          (round_no,)).fetchall():
        old = conn.execute(
            "SELECT i.id, i.student_id, i.company_id FROM interviews i WHERE i.draft_id = %s "
            "AND i.status IN ('PROPOSED', 'INTERVIEWER_CONFIRMED')", (d["id"],)).fetchall()
        ids = [o["id"] for o in old]
        if ids:
            conn.execute(
                "UPDATE availability_slots SET status = 'FREE' WHERE status = 'HELD' AND id IN "
                "(SELECT slot_id FROM interview_panel WHERE interview_id = ANY(%s))", (ids,))
            for o in old:
                conn.execute(
                    "UPDATE slot_preferences SET status = 'PENDING' WHERE student_id = %s AND company_id = %s "
                    "AND round_no = %s AND status = 'MATCHED'", (o["student_id"], o["company_id"], round_no))
            conn.execute("DELETE FROM interviews WHERE id = ANY(%s)", (ids,))
        conn.execute("UPDATE schedule_drafts SET status = 'SUPERSEDED' WHERE id = %s", (d["id"],))


def _company_input(conn, company_id: int, round_no: int, taken: dict) -> dict:
    skill = ROUND_SKILL[round_no]
    slots = conn.execute(
        """
        SELECT s.id, s.interviewer_id, s.start_ts, s.end_ts, s.room_id, iv.skill_tags
        FROM availability_slots s JOIN interviewers iv ON iv.user_id = s.interviewer_id
        WHERE iv.company_id = %s AND iv.is_active AND s.status = 'FREE' AND s.room_id IS NOT NULL
          AND s.start_ts > now() AND %s = ANY(iv.skill_tags)
        ORDER BY s.start_ts, s.id
        """, (company_id, skill)).fetchall()
    slot_ids = {s["id"] for s in slots}
    prefs = conn.execute(
        "SELECT student_id, slot_id, rank FROM slot_preferences WHERE company_id = %s AND round_no = %s "
        "AND status = 'PENDING' ORDER BY student_id, rank", (company_id, round_no)).fetchall()
    slot_by_id = {s["id"]: s for s in slots}
    students = {}
    for p in prefs:
        entry = students.setdefault(p["student_id"], [])
        s = slot_by_id.get(p["slot_id"])
        if s is None:
            continue
        # a student already assigned to another company in this run cannot overlap in time
        if any(s["start_ts"] < e and b < s["end_ts"] for b, e in taken.get(p["student_id"], [])):
            continue
        entry.append({"slotId": p["slot_id"], "rank": p["rank"]})
    room_ids = sorted({s["room_id"] for s in slots})
    return {
        "roundNo": round_no,
        "slots": [{"slotId": s["id"], "interviewerId": s["interviewer_id"], "start": db.iso(s["start_ts"]),
                   "end": db.iso(s["end_ts"]), "roomId": s["room_id"], "skillTags": list(s["skill_tags"])} for s in slots],
        "rooms": [{"roomId": r} for r in room_ids],
        "students": [{"studentId": sid, "prefs": pl} for sid, pl in sorted(students.items())],
        "panelRequirements": {"companyId": company_id, "requiredSkills": []},
        "weights": dict(DEFAULT_WEIGHTS),
    }, slot_by_id


def solve_round(round_no: int) -> dict:
    """Load PENDING preferences + free slots -> build the 4.4 dict per company -> solve -> save a new
    DRAFT version with PROPOSED interviews. All in ONE transaction, serialised per round."""
    solve_batch, _ = get_solver()
    touched_companies, unmatched_total, matched_total = set(), 0, 0
    with db.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (4200 + round_no,))
        _release_old_drafts(conn, round_no)
        companies = [r["company_id"] for r in conn.execute(
            "SELECT DISTINCT company_id FROM slot_preferences WHERE round_no = %s AND status = 'PENDING' "
            "ORDER BY company_id", (round_no,)).fetchall()]
        if not companies:
            return {"draftId": None, "message": "No pending preferences for this round"}

        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM schedule_drafts WHERE round_no = %s",
                               (round_no,)).fetchone()["v"]
        draft = conn.execute(
            "INSERT INTO schedule_drafts (round_no, version, status) VALUES (%s, %s, 'DRAFT') RETURNING id",
            (round_no, version)).fetchone()
        draft_id = draft["id"]
        taken, unmatched_list, objective = {}, [], 0

        for company_id in companies:
            data, slot_by_id = _company_input(conn, company_id, round_no, taken)
            result = solve_batch(data, settings.solver_time_limit)
            objective += result.get("objectiveValue", 0) if result.get("status") in ("OPTIMAL", "FEASIBLE") else 0
            touched_companies.add(company_id)

            for a in result.get("assignments", []):
                base = slot_by_id[a["slotId"]]
                interview = conn.execute(
                    """INSERT INTO interviews (student_id, company_id, round_no, type, start_ts, end_ts, room_id, status, version, draft_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'PROPOSED', 1, %s) RETURNING id""",
                    (a["studentId"], company_id, round_no, "PANEL" if len(a["interviewerIds"]) > 1 else "ONE_ON_ONE",
                     base["start_ts"], base["end_ts"], a.get("roomId") or base["room_id"], draft_id)).fetchone()
                for iv_id in a["interviewerIds"]:       # a one-on-one is a panel of one
                    pslot = base if iv_id == base["interviewer_id"] else conn.execute(
                        "SELECT id, start_ts, end_ts FROM availability_slots WHERE interviewer_id = %s AND start_ts = %s",
                        (iv_id, base["start_ts"])).fetchone()
                    pid = pslot["id"]
                    conn.execute(
                        "INSERT INTO interview_panel (interview_id, interviewer_id, slot_id, start_ts, end_ts) "
                        "VALUES (%s, %s, %s, %s, %s)", (interview["id"], iv_id, pid, base["start_ts"], base["end_ts"]))
                    conn.execute("UPDATE availability_slots SET status = 'HELD' WHERE id = %s AND status = 'FREE'", (pid,))
                conn.execute(
                    "UPDATE slot_preferences SET status = 'MATCHED' WHERE student_id = %s AND company_id = %s "
                    "AND round_no = %s AND slot_id = %s", (a["studentId"], company_id, round_no, a["slotId"]))
                taken.setdefault(a["studentId"], []).append((base["start_ts"], base["end_ts"]))
                matched_total += 1

            for u in result.get("unmatched", []):
                conn.execute(
                    "UPDATE slot_preferences SET status = 'UNMATCHED' WHERE student_id = %s AND company_id = %s "
                    "AND round_no = %s AND status = 'PENDING'", (u["studentId"], company_id, round_no))
                unmatched_list.append({"studentId": u["studentId"], "companyId": company_id, "reason": u["reason"]})
                notify.enqueue_notify(
                    conn, u["studentId"], "MATCH_FAILED",
                    "No slot fits your choices — please choose new slots.", None, {"reason": u["reason"]},
                    email_subject="Please choose new interview slots")
            unmatched_total += len(result.get("unmatched", []))

        conn.execute(
            "UPDATE schedule_drafts SET objective_value = %s, matched = %s, unmatched = %s WHERE id = %s",
            (objective, matched_total, db.jsonb(unmatched_list), draft_id))

        # tell interviewers they have proposals to review
        for r in conn.execute(
                "SELECT DISTINCT p.interviewer_id, count(*) OVER (PARTITION BY p.interviewer_id) AS n "
                "FROM interview_panel p JOIN interviews i ON i.id = p.interview_id WHERE i.draft_id = %s", (draft_id,)).fetchall():
            notify.enqueue_notify(conn, r["interviewer_id"], "NOTICE",
                                  f"{r['n']} new interview proposal(s) are waiting for you. Open Proposals to accept or decline them.",
                                  email_subject="New interview proposals to review")

    for cid in touched_companies:
        cache.invalidate_company_slots(cid)
    notify.kick_outbox()
    return {"draftId": draft_id, "version": version, "matched": matched_total, "unmatched": unmatched_total}
