"""Pass/Fail results with a configurable release delay, and next-round routing (Coding -> Tech -> HR).

Declared results are hidden from the student until release_at (config.result_delay_minutes).
On release: a PASS adds the round to students.passed_rounds (enabling next-round scheduling),
a FAIL ends that pipeline. scheduler.pipeline is used for the routing maths when available."""
import logging
from datetime import datetime, timedelta, timezone

from app import db
from app.errors import ApiError
from app.services import notification_service as notify
from app.services.views import ROUND_SKILL

log = logging.getLogger("trials.results")


def result_delay_minutes(conn) -> int:
    row = conn.execute("SELECT value FROM config WHERE key = 'result_delay_minutes'").fetchone()
    try:
        return max(0, int(row["value"])) if row else 30
    except ValueError:
        return 30


def compute_release_time(declared_at: datetime, delay_minutes: int) -> datetime:
    try:
        from scheduler.pipeline import release_time          # stretch module (optional)
        out = release_time(declared_at, delay_minutes)
        if isinstance(out, datetime):
            return out
    except Exception:  # noqa: BLE001
        pass
    return declared_at + timedelta(minutes=delay_minutes)


def next_round_for(history: list, round_no: int) -> bool:
    """history = [{'roundNo': 1, 'verdict': 'PASS'}, ...]; True if the student may enter round_no."""
    try:
        from scheduler.pipeline import eligible_for_next_round
        return bool(eligible_for_next_round(history, round_no))
    except Exception:  # noqa: BLE001
        by_round = {h["roundNo"]: h["verdict"] for h in history}
        return round_no == 1 or by_round.get(round_no - 1) == "PASS"


def declare_result(interview_id: int, interviewer_id: int, verdict: str, score) -> dict:
    with db.transaction() as conn:
        iv = conn.execute("SELECT id, status, student_id, company_id, round_no FROM interviews WHERE id = %s FOR UPDATE",
                          (interview_id,)).fetchone()
        if not iv:
            raise ApiError("NOT_FOUND", "Interview not found")
        if not conn.execute("SELECT 1 FROM interview_panel WHERE interview_id = %s AND interviewer_id = %s",
                            (interview_id, interviewer_id)).fetchone():
            raise ApiError("FORBIDDEN", "You are not on this interview")
        if iv["status"] not in ("CONFIRMED", "COMPLETED"):
            raise ApiError("VALIDATION", "Only confirmed interviews can receive a result")
        if conn.execute("SELECT 1 FROM results WHERE interview_id = %s", (interview_id,)).fetchone():
            raise ApiError("DUPLICATE", "A result was already recorded for this interview")
        now = datetime.now(timezone.utc)
        release_at = compute_release_time(now, result_delay_minutes(conn))
        conn.execute("INSERT INTO results (interview_id, verdict, score, declared_at, release_at) VALUES (%s, %s, %s, %s, %s)",
                     (interview_id, verdict, score, now, release_at))
        conn.execute("UPDATE interviews SET status = 'COMPLETED' WHERE id = %s", (interview_id,))
    release_due_results()          # delay 0 -> visible immediately; otherwise the beat task does it
    return {"interviewId": interview_id, "verdict": verdict, "score": score,
            "declaredAt": db.iso(now), "releaseAt": db.iso(release_at)}


def release_due_results() -> int:
    """Release every result whose delay has elapsed. Used by release_results_task and after declare."""
    released = 0
    with db.transaction() as conn:
        rows = conn.execute(
            """SELECT r.interview_id, r.verdict, i.student_id, i.round_no, c.name AS company_name
               FROM results r JOIN interviews i ON i.id = r.interview_id JOIN companies c ON c.id = i.company_id
               WHERE NOT r.released AND r.release_at <= now() ORDER BY r.release_at FOR UPDATE OF r SKIP LOCKED""").fetchall()
        for r in rows:
            conn.execute("UPDATE results SET released = true WHERE interview_id = %s", (r["interview_id"],))
            if r["verdict"] == "PASS":
                conn.execute(
                    "UPDATE students SET passed_rounds = CASE WHEN %s = ANY(passed_rounds) THEN passed_rounds "
                    "ELSE array_append(passed_rounds, %s) END WHERE user_id = %s", (r["round_no"], r["round_no"], r["student_id"]))
                nxt = r["round_no"] + 1
                tail = (f" You can now pick slots for the {ROUND_SKILL[nxt]} round." if nxt in ROUND_SKILL else " You have cleared every round!")
                msg = f"{r['company_name']} {ROUND_SKILL.get(r['round_no'])} round: PASS.{tail}"
            else:
                msg = f"{r['company_name']} {ROUND_SKILL.get(r['round_no'])} round: your result is FAIL. Thank you for taking part."
            notify.enqueue_notify(conn, r["student_id"], "RESULT_RELEASED", msg, r["interview_id"], {"verdict": r["verdict"]},
                              email_subject="Your interview result")
            released += 1
    if released:
        notify.kick_outbox()
    return released
