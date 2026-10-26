"""Student preferences. Submitting does NO heavy work (invariant 2): validate, one transaction,
immediate {"status": "PENDING"}. The solver only ever runs in a Celery worker."""
from app import db
from app.errors import ApiError
from app.services import views
from app.services.views import ROUND_SKILL

LIVE_STATUSES = ("PROPOSED", "INTERVIEWER_CONFIRMED", "CONFIRMED", "FLAGGED", "COMPLETED")


def validate_choices(choices) -> list:
    """Pure function (unit-tested): 1-3 choices, ranks unique and in 1..3, slots unique."""
    if not 1 <= len(choices) <= 3:
        raise ApiError("VALIDATION", "Choose between 1 and 3 slots")
    ranks = [c.rank for c in choices]
    if any(r not in (1, 2, 3) for r in ranks):
        raise ApiError("VALIDATION", "Ranks must be 1, 2 or 3")
    if len(set(ranks)) != len(ranks):
        raise ApiError("VALIDATION", "Each rank can be used only once")
    slot_ids = [c.slot_id for c in choices]
    if len(set(slot_ids)) != len(slot_ids):
        raise ApiError("VALIDATION", "The same slot cannot be chosen twice")
    return sorted(choices, key=lambda c: c.rank)


def eligible_for_round(passed_rounds, round_no: int) -> bool:
    """Coding -> Tech -> HR. Round 1 is open to all; round n needs a released PASS in round n-1."""
    if round_no == 1:
        return True
    return (round_no - 1) in (passed_rounds or [])


def submit(student_id: int, body, idem_key: str) -> dict:
    choices = validate_choices(body.choices)
    with db.transaction() as conn:
        company = conn.execute("SELECT id FROM companies WHERE id = %s", (body.company_id,)).fetchone()
        if not company:
            raise ApiError("NOT_FOUND", "Company not found")
        st = conn.execute("SELECT passed_rounds FROM students WHERE user_id = %s", (student_id,)).fetchone()
        if not st:
            raise ApiError("FORBIDDEN", "Student profile missing")
        if not eligible_for_round(st["passed_rounds"], body.round_no):
            raise ApiError("VALIDATION", "You have not cleared the previous round yet")

        live = conn.execute(
            "SELECT 1 FROM interviews WHERE student_id = %s AND company_id = %s AND round_no = %s "
            "AND status = ANY(%s)", (student_id, body.company_id, body.round_no, list(LIVE_STATUSES))).fetchone()
        if live:
            raise ApiError("DUPLICATE", "You already have an interview for this company and round")

        slot_ids = [c.slot_id for c in choices]
        # Plain read, deliberately NO row locks: a preference reserves nothing (the slot is only HELD/BOOKED by the
        # solver / approval). Locking here deadlocked with matching under load; the DB constraints are the final guard.
        rows = conn.execute(
            """
            SELECT s.id, s.status, s.start_ts, iv.company_id, iv.skill_tags, iv.is_active, s.room_id
            FROM availability_slots s JOIN interviewers iv ON iv.user_id = s.interviewer_id
            WHERE s.id = ANY(%s)
            """, (slot_ids,)).fetchall()
        by_id = {r["id"]: r for r in rows}
        for sid in slot_ids:
            r = by_id.get(sid)
            if r is None or r["company_id"] != body.company_id:
                raise ApiError("VALIDATION", f"Slot {sid} does not belong to this company")
            if ROUND_SKILL[body.round_no] not in (r["skill_tags"] or []):
                raise ApiError("VALIDATION", f"Slot {sid} is not offered for this round")
            if r["status"] != "FREE" or not r["is_active"] or r["room_id"] is None:
                raise ApiError("SLOT_TAKEN", "Slot just taken, please pick another")

        if conn.execute("SELECT 1 FROM slot_preferences WHERE student_id = %s AND company_id = %s AND round_no = %s "
                        "AND status = 'MATCHED'", (student_id, body.company_id, body.round_no)).fetchone():
            raise ApiError("DUPLICATE", "You are already matched for this round and awaiting approval")
        # replace this student's previous (not yet committed) choices for company+round
        conn.execute("DELETE FROM slot_preferences WHERE student_id = %s AND company_id = %s AND round_no = %s",
                     (student_id, body.company_id, body.round_no))
        for c in choices:
            conn.execute(
                "INSERT INTO slot_preferences (student_id, slot_id, company_id, round_no, rank, status, idempotency_key) "
                "VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)",
                (student_id, c.slot_id, body.company_id, body.round_no, c.rank, f"{student_id}:{idem_key}:{c.rank}"))
    return {"status": "PENDING"}


def status_text(prefs, interviews) -> str:
    committed = [i for i in interviews if i["status"] in ("CONFIRMED", "FLAGGED")]
    if any(i["status"] == "FLAGGED" for i in committed):
        return "Your interview is being rescheduled — you will be notified shortly."
    upcoming = sorted((i for i in committed), key=lambda i: i["start"])
    if upcoming:
        i = upcoming[0]
        return (f"Interview confirmed: {i['companyName']} ({ROUND_SKILL.get(i['roundNo'])}) "
                f"on {views.human_time(i['start'])}.")
    statuses = {p["status"] for p in prefs}
    if "MATCHED" in statuses:
        return "Matched — waiting for the coordinator's final approval."
    if "PENDING" in statuses:
        return "Pending — your ranked slots are submitted; matching has not run yet."
    if "UNMATCHED" in statuses:
        return "No slot fit your choices — please pick new slots."
    if any(i["status"] == "COMPLETED" for i in interviews):
        return "Interview completed — results will appear once released."
    return "No slots chosen yet — browse companies and rank up to 3 slots."


def student_status(student_id: int) -> dict:
    with db.transaction() as conn:
        prefs = conn.execute(
            """
            SELECT p.id, p.slot_id, p.company_id, c.name AS company_name, p.round_no, p.rank, p.status,
                   s.start_ts, s.end_ts, u.name AS interviewer_name
            FROM slot_preferences p
            JOIN companies c ON c.id = p.company_id
            JOIN availability_slots s ON s.id = p.slot_id
            JOIN users u ON u.id = s.interviewer_id
            WHERE p.student_id = %s AND p.status <> 'CANCELLED'
            ORDER BY p.company_id, p.round_no, p.rank
            """, (student_id,)).fetchall()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM interviews WHERE student_id = %s AND status IN ('CONFIRMED','FLAGGED','COMPLETED') "
            "ORDER BY start_ts", (student_id,)).fetchall()]
        interviews = views.interviews_by_ids(conn, ids)
        results = conn.execute(
            """SELECT r.interview_id, r.verdict, r.score, r.release_at, i.company_id, c.name AS company_name, i.round_no
               FROM results r JOIN interviews i ON i.id = r.interview_id JOIN companies c ON c.id = i.company_id
               WHERE i.student_id = %s AND r.released ORDER BY r.release_at DESC""", (student_id,)).fetchall()
        passed = conn.execute("SELECT passed_rounds FROM students WHERE user_id = %s", (student_id,)).fetchone()
        pending = conn.execute(
            """SELECT r.interview_id, r.release_at FROM results r JOIN interviews i ON i.id = r.interview_id
               WHERE i.student_id = %s AND NOT r.released ORDER BY r.release_at""", (student_id,)).fetchall()
    preferences = [{
        "id": p["id"], "slotId": p["slot_id"], "companyId": p["company_id"], "companyName": p["company_name"],
        "roundNo": p["round_no"], "rank": p["rank"], "status": p["status"],
        "start": db.iso(p["start_ts"]), "end": db.iso(p["end_ts"]), "interviewerNames": [p["interviewer_name"]],
    } for p in prefs]
    return {
        "preferences": preferences,
        "interviews": interviews,
        "statusText": status_text(preferences, interviews),
        "results": [{"interviewId": r["interview_id"], "companyId": r["company_id"], "companyName": r["company_name"],
                     "roundNo": r["round_no"], "verdict": r["verdict"], "score": float(r["score"]) if r["score"] is not None else None,
                     "releasedAt": db.iso(r["release_at"])} for r in results],
        "passedRounds": (passed or {}).get("passed_rounds", []),
        "pendingResults": [{"interviewId": r["interview_id"], "releaseAt": db.iso(r["release_at"])} for r in pending],
    }
