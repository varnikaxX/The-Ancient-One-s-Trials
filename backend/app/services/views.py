"""Builders for the shared `interview` object (contract 4.3):
{id, studentId, studentName, companyId, companyName, roundNo, type, start, end, room, status, version,
 panel:[{interviewerId, name, skill}]}"""
from typing import Dict, Iterable, List

from app import db

ROUND_SKILL = {1: "Coding", 2: "Tech", 3: "HR"}


def interviews_by_ids(conn, ids: Iterable[int]) -> List[dict]:
    ids = list(ids)
    if not ids:
        return []
    rows = conn.execute(
        """
        SELECT i.id, i.student_id, su.name AS student_name, i.company_id, c.name AS company_name,
               i.round_no, i.type, i.start_ts, i.end_ts, r.name AS room_name, i.status, i.version
        FROM interviews i
        JOIN users su ON su.id = i.student_id
        JOIN companies c ON c.id = i.company_id
        LEFT JOIN rooms r ON r.id = i.room_id
        WHERE i.id = ANY(%s)
        ORDER BY i.start_ts, i.id
        """, (ids,)).fetchall()
    panel_rows = conn.execute(
        """
        SELECT p.interview_id, p.interviewer_id, u.name, iv.skill_tags
        FROM interview_panel p
        JOIN users u ON u.id = p.interviewer_id
        JOIN interviewers iv ON iv.user_id = p.interviewer_id
        WHERE p.interview_id = ANY(%s)
        ORDER BY p.interview_id, p.interviewer_id
        """, (ids,)).fetchall()
    panels: Dict[int, list] = {}
    for p in panel_rows:
        panels.setdefault(p["interview_id"], []).append(p)
    out = []
    for r in rows:
        want = ROUND_SKILL.get(r["round_no"])
        panel = []
        for p in panels.get(r["id"], []):
            tags = p["skill_tags"] or []
            skill = want if want in tags else (tags[0] if tags else None)
            panel.append({"interviewerId": p["interviewer_id"], "name": p["name"], "skill": skill})
        out.append({
            "id": r["id"], "studentId": r["student_id"], "studentName": r["student_name"],
            "companyId": r["company_id"], "companyName": r["company_name"], "roundNo": r["round_no"],
            "type": r["type"], "start": db.iso(r["start_ts"]), "end": db.iso(r["end_ts"]),
            "room": r["room_name"], "status": r["status"], "version": r["version"], "panel": panel,
        })
    return out


def interview_by_id(conn, interview_id: int):
    rows = interviews_by_ids(conn, [interview_id])
    return rows[0] if rows else None


def human_time(start_iso: str) -> str:
    """'2026-11-03T09:00:00Z' -> '03 Nov 2026, 09:00 UTC' for messages."""
    dt = db.parse_iso(start_iso)
    return dt.strftime("%d %b %Y, %H:%M UTC")
