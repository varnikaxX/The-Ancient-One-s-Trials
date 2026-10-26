"""Interviewer confirmation + coordinator approval (the commit).

approve_draft = ONE transaction (invariants 1, 3, 4):
  lock draft -> version check (STALE_DRAFT) -> SELECT ... FOR UPDATE on slots -> slots BOOKED,
  interviews CONFIRMED, panel rows booked -> outbox rows (email + in-app per student & panelist) -> commit.
Unique/exclusion violations (the DB is the final guard) surface as SLOT_TAKEN.
"""
from app import db
from app.errors import ApiError
from app.services import cache, notification_service as notify, views
from app.services.views import ROUND_SKILL


def proposals_for(interviewer_id: int) -> list:
    with db.transaction() as conn:
        ids = [r["id"] for r in conn.execute(
            """SELECT i.id FROM interviews i JOIN interview_panel p ON p.interview_id = i.id
               WHERE p.interviewer_id = %s AND i.status = 'PROPOSED' AND NOT p.confirmed ORDER BY i.start_ts""",
            (interviewer_id,)).fetchall()]
        return views.interviews_by_ids(conn, ids)


def interviewer_confirm(interview_id: int, interviewer_id: int) -> dict:
    with db.transaction() as conn:
        iv = conn.execute("SELECT id, status FROM interviews WHERE id = %s FOR UPDATE", (interview_id,)).fetchone()
        if not iv:
            raise ApiError("NOT_FOUND", "Interview not found")
        mine = conn.execute("SELECT confirmed FROM interview_panel WHERE interview_id = %s AND interviewer_id = %s",
                            (interview_id, interviewer_id)).fetchone()
        if not mine:
            raise ApiError("FORBIDDEN", "You are not on this interview")
        if iv["status"] in ("INTERVIEWER_CONFIRMED", "CONFIRMED"):
            return views.interview_by_id(conn, interview_id)          # idempotent
        if iv["status"] != "PROPOSED":
            raise ApiError("VALIDATION", f"Interview is {iv['status']} and cannot be confirmed")
        conn.execute("UPDATE interview_panel SET confirmed = true WHERE interview_id = %s AND interviewer_id = %s",
                     (interview_id, interviewer_id))
        pending = conn.execute("SELECT count(*) AS n FROM interview_panel WHERE interview_id = %s AND NOT confirmed",
                               (interview_id,)).fetchone()["n"]
        if pending == 0:
            conn.execute("UPDATE interviews SET status = 'INTERVIEWER_CONFIRMED' WHERE id = %s", (interview_id,))
        return views.interview_by_id(conn, interview_id)


def _announce(conn, interview: dict, type_: str, headline: str, who_students=True):
    """Outbox rows: in-app + email for the student and each panelist."""
    when = views.human_time(interview["start"])
    rnd = ROUND_SKILL.get(interview["roundNo"])
    names = ", ".join(p["name"] for p in interview["panel"])
    msg_student = f"{headline}: {interview['companyName']} {rnd} interview on {when}. Interviewer(s): {names}."
    msg_panel = f"{headline}: {interview['companyName']} {rnd} interview with {interview['studentName']} on {when}."
    recipients = []
    if who_students:
        recipients.append((interview["studentId"], msg_student))
    recipients += [(p["interviewerId"], msg_panel) for p in interview["panel"]]
    for uid, msg in recipients:
        notify.enqueue_notify(conn, uid, type_, msg, interview["id"])
        user = conn.execute("SELECT email FROM users WHERE id = %s", (uid,)).fetchone()
        notify.enqueue_email(conn, user["email"], f"{headline} — {interview['companyName']}", msg + "\n\nThe calendar invite (.ics) is attached.", interview["id"])


def approve_draft(draft_id: int, version: int) -> dict:
    companies = set()
    try:
        with db.transaction() as conn:
            draft = conn.execute("SELECT * FROM schedule_drafts WHERE id = %s FOR UPDATE", (draft_id,)).fetchone()
            if not draft:
                raise ApiError("NOT_FOUND", "Draft not found")
            latest = conn.execute("SELECT MAX(version) AS v FROM schedule_drafts WHERE round_no = %s",
                                  (draft["round_no"],)).fetchone()["v"]
            if draft["status"] != "DRAFT" or draft["version"] != version or version != latest:
                raise ApiError("STALE_DRAFT", "This draft is outdated — refresh to see the latest version")

            iv_rows = conn.execute(
                "SELECT id, status FROM interviews WHERE draft_id = %s AND status IN ('PROPOSED', 'INTERVIEWER_CONFIRMED') "
                "ORDER BY id FOR UPDATE", (draft_id,)).fetchall()
            waiting = [r for r in iv_rows if r["status"] == "PROPOSED"]
            if waiting:
                raise ApiError("VALIDATION", f"{len(waiting)} interview(s) are still waiting for the interviewer to confirm")
            ids = [r["id"] for r in iv_rows]
            slot_ids = [r["slot_id"] for r in conn.execute(
                "SELECT DISTINCT slot_id FROM interview_panel WHERE interview_id = ANY(%s) ORDER BY slot_id", (ids,)).fetchall()]
            locked = conn.execute("SELECT id, status FROM availability_slots WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                                  (slot_ids,)).fetchall()
            if len(locked) != len(slot_ids) or any(s["status"] == "BOOKED" for s in locked):
                raise ApiError("SLOT_TAKEN", "A slot in this draft was just taken — please re-run matching")

            conn.execute("UPDATE availability_slots SET status = 'BOOKED' WHERE id = ANY(%s)", (slot_ids,))
            conn.execute("UPDATE interview_panel SET booked = true, confirmed = true WHERE interview_id = ANY(%s)", (ids,))
            conn.execute("UPDATE interviews SET status = 'CONFIRMED' WHERE id = ANY(%s)", (ids,))
            conn.execute("UPDATE schedule_drafts SET status = 'APPROVED' WHERE id = %s", (draft_id,))

            interviews = views.interviews_by_ids(conn, ids)
            for it in interviews:
                companies.add(it["companyId"])
                # chosen preference stays MATCHED, the student's other ranked slots are closed
                conn.execute(
                    "UPDATE slot_preferences SET status = 'CANCELLED' WHERE student_id = %s AND company_id = %s "
                    "AND round_no = %s AND status <> 'MATCHED'", (it["studentId"], it["companyId"], it["roundNo"]))
                _announce(conn, it, "INTERVIEW_CONFIRMED", "Interview confirmed")
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001
        if db.is_integrity_error(exc):
            raise ApiError("SLOT_TAKEN", "Slot just taken, please pick another")
        raise
    for cid in companies:
        cache.invalidate_company_slots(cid)
    notify.kick_outbox()
    return {"committed": len(ids)}
