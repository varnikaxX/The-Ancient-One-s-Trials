"""Slot generation & availability.

Rule: a slot is bookable only if its interviewer is free (they declared it) AND a room is free
at that time (a room_id is assigned when the slot is created). No free room -> no slot.
"""
from datetime import datetime, timedelta, timezone
from typing import List

from app import db
from app.config import settings
from app.errors import ApiError
from app.services import cache
from app.services.views import ROUND_SKILL

ROOM_LOCK = 7001  # advisory lock id: serialises room assignment


def chunk_ranges(ranges, now: datetime = None) -> List[datetime]:
    """[{start,end}] -> sorted unique list of slot start datetimes (SLOT_MINUTES long, future only)."""
    now = now or datetime.now(timezone.utc)
    step = timedelta(minutes=settings.slot_minutes)
    starts = set()
    for r in ranges:
        try:
            s, e = db.parse_iso(r.start), db.parse_iso(r.end)
        except ValueError as exc:
            raise ApiError("VALIDATION", str(exc))
        if e <= s:
            raise ApiError("VALIDATION", "Slot end must be after start")
        if e - s > timedelta(days=1):
            raise ApiError("VALIDATION", "A single availability range cannot exceed 24 hours")
        t = s
        while t + step <= e:
            if t > now:
                starts.add(t)
            t += step
    return sorted(starts)


def _free_room(conn, start, end):
    row = conn.execute(
        """
        SELECT r.id FROM rooms r
        WHERE NOT EXISTS (
            SELECT 1 FROM availability_slots s
            WHERE s.room_id = r.id AND tstzrange(s.start_ts, s.end_ts) && tstzrange(%s, %s))
        ORDER BY r.id LIMIT 1
        """, (start, end)).fetchone()
    return row["id"] if row else None


def slot_dict(row) -> dict:
    return {"slotId": row["id"], "start": db.iso(row["start_ts"]), "end": db.iso(row["end_ts"]),
            "status": row["status"], "room": row.get("room_name")}


def interviewer_future_slots(conn, interviewer_id: int) -> List[dict]:
    rows = conn.execute(
        """SELECT s.id, s.start_ts, s.end_ts, s.status, r.name AS room_name
           FROM availability_slots s LEFT JOIN rooms r ON r.id = s.room_id
           WHERE s.interviewer_id = %s AND s.start_ts > now() ORDER BY s.start_ts""", (interviewer_id,)).fetchall()
    return [slot_dict(r) for r in rows]


def replace_availability(interviewer_id: int, ranges) -> List[dict]:
    """PUT /interviewer/availability: replaces the interviewer's future FREE slots."""
    starts = chunk_ranges(ranges)
    step = timedelta(minutes=settings.slot_minutes)
    with db.transaction() as conn:
        iv = conn.execute("SELECT company_id, is_active FROM interviewers WHERE user_id = %s FOR UPDATE",
                          (interviewer_id,)).fetchone()
        if not iv:
            raise ApiError("NOT_FOUND", "Interviewer profile not found")
        if not iv["company_id"]:
            raise ApiError("VALIDATION", "Set your company and skills before declaring availability")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (ROOM_LOCK,))

        # drop future FREE slots that are no longer offered (HELD / BOOKED are never touched)
        conn.execute(
            "DELETE FROM availability_slots WHERE interviewer_id = %s AND status = 'FREE' "
            "AND start_ts > now() AND NOT (start_ts = ANY(%s::timestamptz[]))", (interviewer_id, starts))
        # add new ones that have a room
        for st in starts:
            exists = conn.execute("SELECT 1 FROM availability_slots WHERE interviewer_id = %s AND start_ts = %s",
                                  (interviewer_id, st)).fetchone()
            if exists:
                continue
            room_id = _free_room(conn, st, st + step)
            if room_id is None:
                continue  # no room free -> not bookable
            conn.execute(
                "INSERT INTO availability_slots (interviewer_id, start_ts, end_ts, status, room_id) "
                "VALUES (%s, %s, %s, 'FREE', %s)", (interviewer_id, st, st + step, room_id))
        result = interviewer_future_slots(conn, interviewer_id)
    cache.invalidate_company_slots(iv["company_id"])
    return result


def list_company_slots(company_id: int, round_no: int) -> List[dict]:
    """GET /companies/{id}/slots?roundNo= — only FREE, future, room-assigned slots whose interviewer
    can assess that round. Cached in Redis under slots:{companyId}:{roundNo}."""
    if round_no not in ROUND_SKILL:
        raise ApiError("VALIDATION", "roundNo must be 1, 2 or 3")
    key = cache.slots_key(company_id, round_no)
    cached = cache.cache_get(key)
    if cached is not None:
        return cached
    rows = db.fetchall(
        """
        SELECT s.id, s.start_ts, s.end_ts, u.name AS interviewer_name, r.name AS room_name
        FROM availability_slots s
        JOIN interviewers iv ON iv.user_id = s.interviewer_id
        JOIN users u ON u.id = iv.user_id
        JOIN rooms r ON r.id = s.room_id
        WHERE iv.company_id = %s AND iv.is_active AND s.status = 'FREE' AND s.start_ts > now()
          AND %s = ANY(iv.skill_tags)
        ORDER BY s.start_ts, s.id
        """, (company_id, ROUND_SKILL[round_no]))
    data = [{"slotId": r["id"], "start": db.iso(r["start_ts"]), "end": db.iso(r["end_ts"]),
             "interviewerNames": [r["interviewer_name"]], "room": r["room_name"]} for r in rows]
    cache.cache_set(key, data)
    return data
