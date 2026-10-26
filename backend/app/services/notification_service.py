"""In-app notifications. Rows live in `notifications`; live delivery = Redis channel user:{id}.

Business code never delivers directly: it writes OUTBOX rows inside its own transaction
(enqueue_notify / enqueue_email) and the Celery outbox worker delivers them (invariant 4).
"""
import logging

from app import db
from app.services import cache

log = logging.getLogger("trials.notify")

TYPES = {"INTERVIEW_CONFIRMED", "INTERVIEW_CHANGED", "INTERVIEW_CANCELLED", "REMINDER",
         "MATCH_FAILED", "NOTICE", "RESULT_RELEASED"}


def enqueue_notify(conn, user_id: int, type_: str, message: str, interview_id=None, extra=None, email_subject=None):
    """In-app notification via the outbox. With email_subject the same text is also emailed (no .ics)."""
    payload = {"interviewId": interview_id, "message": message}
    if extra:
        payload.update(extra)
    conn.execute(
        "INSERT INTO outbox (kind, payload) VALUES ('NOTIFY', %s)",
        (db.jsonb({"userId": user_id, "type": type_, "payload": payload}),),
    )
    if email_subject:
        row = conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()
        if row:
            enqueue_email(conn, row["email"], email_subject, message)


def enqueue_email(conn, to: str, subject: str, text: str, interview_id=None):
    conn.execute(
        "INSERT INTO outbox (kind, payload) VALUES ('EMAIL', %s)",
        (db.jsonb({"to": to, "subject": subject, "text": text, "interviewId": interview_id}),),
    )


def deliver_notify(conn, payload: dict):
    """Insert the row, then publish. Called by the outbox worker (inside its transaction)."""
    row = conn.execute(
        "INSERT INTO notifications (user_id, type, payload, channel) VALUES (%s, %s, %s, 'IN_APP') RETURNING id",
        (payload["userId"], payload["type"], db.jsonb(payload["payload"])),
    ).fetchone()
    cache.publish_user(payload["userId"], payload["type"], dict(payload["payload"], notificationId=row["id"]))
    return row["id"]


def kick_outbox():
    """Ask the worker to drain the outbox now instead of waiting for the 10 s beat.
    Best effort: a down broker must never break a confirmation."""
    try:
        from workers.tasks import deliver_outbox_task
        deliver_outbox_task.delay()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not kick outbox (beat will pick it up): %s", exc)


def list_notifications(user_id: int, limit: int = 100):
    rows = db.fetchall(
        "SELECT id, type, payload, read_at, channel, created_at FROM notifications "
        "WHERE user_id = %s ORDER BY id DESC LIMIT %s", (user_id, limit))
    return [{
        "id": r["id"], "type": r["type"], "payload": r["payload"],
        "message": (r["payload"] or {}).get("message", ""),
        "read": r["read_at"] is not None, "readAt": db.iso(r["read_at"]),
        "channel": r["channel"], "createdAt": db.iso(r["created_at"]),
    } for r in rows]


def mark_read(user_id: int, notification_id: int):
    from app.errors import ApiError
    with db.transaction() as conn:
        row = conn.execute(
            "UPDATE notifications SET read_at = COALESCE(read_at, now()) WHERE id = %s AND user_id = %s RETURNING id",
            (notification_id, user_id)).fetchone()
    if not row:
        raise ApiError("NOT_FOUND", "Notification not found")
    return {"id": notification_id, "read": True}
