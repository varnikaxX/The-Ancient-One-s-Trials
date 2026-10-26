"""Celery tasks. solve_round_task is the ONLY place the solver runs (invariant 2)."""
import logging
from datetime import datetime, timezone

from app import db
from app.config import settings
from workers.celery_app import celery

log = logging.getLogger("trials.tasks")


@celery.task(name="workers.tasks.solve_round_task", bind=True, max_retries=2, default_retry_delay=5)
def solve_round_task(self, round_no: int):
    from app.services import matching_service
    try:
        return matching_service.solve_round(round_no)
    except Exception as exc:  # noqa: BLE001
        log.exception("solve_round failed")
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))


@celery.task(name="workers.tasks.repair_task", bind=True, max_retries=3)
def repair_task(self, interview_ids, cancelled_slot_ids, cancelled_interviewer_id, reason=""):
    from app.services import disruption_service
    try:
        return disruption_service.repair(interview_ids, cancelled_slot_ids, cancelled_interviewer_id, reason)
    except Exception as exc:  # noqa: BLE001
        log.exception("repair failed")
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))


def process_outbox(batch: int = None) -> dict:
    """One pass over PENDING outbox rows. Plain function so tests can call it without Celery.
    Each row is attempted inside its own transaction (SELECT ... FOR UPDATE SKIP LOCKED)."""
    from app.services import email_service, ics_service, notification_service
    batch = batch or settings.outbox_batch
    stats = {"sent": 0, "failed": 0, "retry": 0}
    while True:
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT id, kind, payload, attempts FROM outbox WHERE status = 'PENDING' "
                "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
            if not row or sum(stats.values()) >= batch:
                return stats
            try:
                if row["kind"] == "NOTIFY":
                    notification_service.deliver_notify(conn, row["payload"])
                else:
                    p = row["payload"]
                    ics = None
                    if p.get("interviewId"):
                        try:
                            ics = ics_service.build_ics(p["interviewId"])
                        except Exception:  # noqa: BLE001  (a missing ICS never blocks the email)
                            ics = None
                    email_service.send_email(p["to"], p["subject"], p["text"], ics)
                conn.execute("UPDATE outbox SET status = 'SENT', attempts = attempts + 1, last_error = NULL WHERE id = %s", (row["id"],))
                stats["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                attempts = row["attempts"] + 1
                final = attempts >= settings.outbox_max_attempts
                conn.execute("UPDATE outbox SET status = %s, attempts = %s, last_error = %s WHERE id = %s",
                             ("FAILED" if final else "PENDING", attempts, str(exc)[:500], row["id"]))
                stats["failed" if final else "retry"] += 1
                if not final:
                    # park the row at the back of the queue so one bad email never blocks others
                    conn.execute("UPDATE outbox SET created_at = now() WHERE id = %s", (row["id"],))
                    return stats      # back off until the next beat (10 s)


@celery.task(name="workers.tasks.deliver_outbox_task")
def deliver_outbox_task():
    return process_outbox()


@celery.task(name="workers.tasks.send_reminders_task")
def send_reminders_task():
    """In-app reminders 24 h and 1 h ahead. Dedup via notifications payload (kind, interviewId, hours)."""
    sent = 0
    for hours in settings.reminder_hours:
        with db.transaction() as conn:
            rows = conn.execute(
                """SELECT i.id, i.student_id, i.start_ts, c.name AS company_name, p.interviewer_id
                   FROM interviews i JOIN companies c ON c.id = i.company_id
                   JOIN interview_panel p ON p.interview_id = i.id
                   WHERE i.status = 'CONFIRMED' AND i.start_ts > now()
                     AND i.start_ts <= now() + make_interval(hours => %s)""", (hours,)).fetchall()
            for r in rows:
                for uid in {r["student_id"], r["interviewer_id"]}:
                    exists = conn.execute(
                        "SELECT 1 FROM notifications WHERE user_id = %s AND type = 'REMINDER' "
                        "AND (payload->>'interviewId')::int = %s AND (payload->>'hours')::int = %s", (uid, r["id"], hours)).fetchone()
                    if exists:
                        continue
                    from app.services import notification_service as n
                    when = db.iso(r["start_ts"])
                    n.enqueue_notify(conn, uid, "REMINDER",
                                     f"Reminder: {r['company_name']} interview at {when} (in about {hours}h).",
                                     r["id"], {"hours": hours})
                    sent += 1
    if sent:
        from app.services import notification_service
        notification_service.kick_outbox()
    return {"reminders": sent}


@celery.task(name="workers.tasks.release_results_task")
def release_results_task():
    from app.services import result_service
    return {"released": result_service.release_due_results()}


@celery.task(name="workers.tasks.auto_match_at_deadline_task")
def auto_match_at_deadline_task():
    """When config.matching_deadline has passed, run matching once for every round with pending preferences."""
    row = db.fetchone("SELECT value FROM config WHERE key = 'matching_deadline'")
    if not row or not row["value"].strip():
        return {"ran": []}
    try:
        deadline = db.parse_iso(row["value"])
    except ValueError:
        return {"ran": [], "error": "bad matching_deadline"}
    if datetime.now(timezone.utc) < deadline:
        return {"ran": []}
    with db.transaction() as conn:
        conn.execute("UPDATE config SET value = '' WHERE key = 'matching_deadline'")      # fire once
        rounds = [r["round_no"] for r in conn.execute(
            "SELECT DISTINCT round_no FROM slot_preferences WHERE status = 'PENDING' ORDER BY round_no").fetchall()]
    for rn in rounds:
        solve_round_task.delay(rn)
    return {"ran": rounds}
