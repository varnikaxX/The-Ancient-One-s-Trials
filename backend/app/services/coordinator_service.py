"""Coordinator read models: drafts, draft detail, notices, and the FullCalendar feed."""
from typing import Optional

from app import db
from app.errors import ApiError
from app.services import notification_service as notify, views
from app.services.views import ROUND_SKILL


def _draft_summary(r) -> dict:
    return {"draftId": r["id"], "version": r["version"], "status": r["status"],
            "objectiveValue": float(r["objective_value"]), "matched": r["matched"],
            "unmatched": len(r["unmatched"] or []), "roundNo": r["round_no"]}


def list_drafts(round_no: int) -> list:
    rows = db.fetchall("SELECT * FROM schedule_drafts WHERE round_no = %s ORDER BY version DESC", (round_no,))
    return [_draft_summary(r) for r in rows]


def draft_detail(draft_id: int) -> dict:
    with db.transaction() as conn:
        d = conn.execute("SELECT * FROM schedule_drafts WHERE id = %s", (draft_id,)).fetchone()
        if not d:
            raise ApiError("NOT_FOUND", "Draft not found")
        ids = [r["id"] for r in conn.execute("SELECT id FROM interviews WHERE draft_id = %s AND status <> 'CANCELLED' ORDER BY start_ts, id",
                                             (draft_id,)).fetchall()]
        interviews = views.interviews_by_ids(conn, ids)
        names = {r["id"]: r["name"] for r in conn.execute(
            "SELECT id, name FROM users WHERE id = ANY(%s)", ([u["studentId"] for u in (d["unmatched"] or [])],)).fetchall()}
    unmatched = [{"studentId": u["studentId"], "studentName": names.get(u["studentId"], ""),
                  "companyId": u.get("companyId"), "reason": u["reason"]} for u in (d["unmatched"] or [])]
    return {"draft": _draft_summary(d) | {"createdAt": db.iso(d["created_at"])}, "interviews": interviews,
            "unmatchedStudents": unmatched}


def send_notice(message: str, audience: str) -> dict:
    roles = {"ALL": ("STUDENT", "INTERVIEWER"), "STUDENT": ("STUDENT",), "STUDENTS": ("STUDENT",),
             "INTERVIEWER": ("INTERVIEWER",), "INTERVIEWERS": ("INTERVIEWER",)}[audience]
    with db.transaction() as conn:
        users = conn.execute("SELECT id, email FROM users WHERE role = ANY(%s) ORDER BY id", (list(roles),)).fetchall()
        for u in users:
            notify.enqueue_notify(conn, u["id"], "NOTICE", message)
            notify.enqueue_email(conn, u["email"], "Notice from the placement coordinator", message)
    notify.kick_outbox()
    return {"queued": len(users)}


def calendar_events(user: dict, frm: Optional[str], to: Optional[str]) -> list:
    try:
        f = db.parse_iso(frm) if frm else None
        t = db.parse_iso(to) if to else None
    except ValueError as exc:
        raise ApiError("VALIDATION", str(exc))
    where, params = ["i.status <> 'CANCELLED'"], []
    if user["role"] == "STUDENT":
        where.append("i.student_id = %s AND i.status IN ('CONFIRMED','FLAGGED','COMPLETED')")
        params.append(user["id"])
    elif user["role"] == "INTERVIEWER":
        where.append("EXISTS (SELECT 1 FROM interview_panel p WHERE p.interview_id = i.id AND p.interviewer_id = %s)")
        params.append(user["id"])
    else:
        where.append("i.status IN ('CONFIRMED','FLAGGED','COMPLETED')")
    if f:
        where.append("i.end_ts >= %s")
        params.append(f)
    if t:
        where.append("i.start_ts <= %s")
        params.append(t)
    with db.transaction() as conn:
        ids = [r["id"] for r in conn.execute(f"SELECT i.id FROM interviews i WHERE {' AND '.join(where)} ORDER BY i.start_ts", params).fetchall()]
        interviews = views.interviews_by_ids(conn, ids)
    out = []
    for i in interviews:
        rnd = ROUND_SKILL.get(i["roundNo"], str(i["roundNo"]))
        title = (f"{i['companyName']} — {rnd}" if user["role"] == "STUDENT"
                 else f"{i['companyName']} {rnd}: {i['studentName']}")
        out.append({"id": i["id"], "title": title, "start": i["start"], "end": i["end"], "room": i["room"],
                    "interviewerNames": [p["name"] for p in i["panel"]], "status": i["status"]})
    return out
