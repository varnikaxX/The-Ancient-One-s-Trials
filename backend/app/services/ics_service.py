"""RFC 5545 calendar files via `icalendar`."""
from datetime import datetime, timedelta, timezone

from icalendar import Alarm, Calendar, Event

from app import db
from app.errors import ApiError
from app.services import views

ROUND_NAME = views.ROUND_SKILL


def build_ics_for(interview: dict) -> bytes:
    """interview = the contract interview object."""
    cal = Calendar()
    cal.add("prodid", "-//Ancient One's Trials//Interview Scheduler//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")

    ev = Event()
    ev.add("uid", f"interview-{interview['id']}@ancient-ones-trials")
    ev.add("dtstamp", datetime.now(timezone.utc))
    ev.add("dtstart", db.parse_iso(interview["start"]))
    ev.add("dtend", db.parse_iso(interview["end"]))
    round_name = ROUND_NAME.get(interview["roundNo"], f"Round {interview['roundNo']}")
    ev.add("summary", f"{interview['companyName']} — {round_name} interview")
    if interview.get("room"):
        ev.add("location", interview["room"])
    names = ", ".join(p["name"] for p in interview["panel"]) or "TBA"
    ev.add("description",
           f"Candidate: {interview['studentName']}\nInterviewer(s): {names}\n"
           f"Company: {interview['companyName']}\nRound: {round_name}\nStatus: {interview['status']}")
    ev.add("status", "CONFIRMED" if interview["status"] in ("CONFIRMED", "COMPLETED") else "TENTATIVE")
    ev.add("sequence", interview["version"])      # bumps on reschedule so clients update the event

    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", "Interview starts in 1 hour")
    alarm.add("trigger", -timedelta(hours=1))
    ev.add_component(alarm)

    cal.add_component(ev)
    return cal.to_ical()


def build_ics(interview_id: int) -> bytes:
    with db.transaction() as conn:
        interview = views.interview_by_id(conn, interview_id)
    if not interview:
        raise ApiError("NOT_FOUND", "Interview not found")
    return build_ics_for(interview)


def can_download(user: dict, interview_id: int) -> dict:
    """STUDENT: own interview. INTERVIEWER: panelist. Returns the interview object."""
    with db.transaction() as conn:
        interview = views.interview_by_id(conn, interview_id)
    if not interview or interview["status"] == "CANCELLED":
        raise ApiError("NOT_FOUND", "Interview not found")
    if user["role"] == "STUDENT" and interview["studentId"] == user["id"]:
        return interview
    if user["role"] == "INTERVIEWER" and any(p["interviewerId"] == user["id"] for p in interview["panel"]):
        return interview
    raise ApiError("FORBIDDEN", "This interview is not yours")
