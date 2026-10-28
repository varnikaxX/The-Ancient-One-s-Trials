"""Shared helpers for the scheduler tests (standard library only)."""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
BASE = datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)


def ts(minutes: int) -> str:
    """ISO time `minutes` after 09:00Z on 2026-11-03."""
    return (BASE + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot(slot_id, interviewer_id, minute, room_id=1, tags=("Coding",), length=30):
    return {"slotId": slot_id, "interviewerId": interviewer_id, "start": ts(minute),
            "end": ts(minute + length), "roomId": room_id, "skillTags": list(tags)}


def student(student_id, *slot_ids):
    return {"studentId": student_id,
            "prefs": [{"slotId": s, "rank": i + 1} for i, s in enumerate(slot_ids)]}


def batch(slots, students, rooms=None, required=(), company=1):
    if rooms is None:
        rooms = sorted({s["roomId"] for s in slots if s.get("roomId") is not None})
    return {"roundNo": 1, "slots": slots, "rooms": [{"roomId": r} for r in rooms],
            "students": students,
            "panelRequirements": {"companyId": company, "requiredSkills": list(required)},
            "weights": {"rank1": 100, "rank2": 60, "rank3": 30, "unmatchedPenalty": 1000}}


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def big_scenario(n_students=200, n_slots=60, seed=7):
    """n_slots slots over 6 interviewers / 3 rooms; each student ranks 3 slots."""
    rng = random.Random(seed)
    slots = []
    for i in range(n_slots):
        interviewer = 100 + i % 6
        minute = (i // 6) * 30
        slots.append(slot(i + 1, interviewer, minute, room_id=1 + i % 3))
    # rooms: 3 rooms but 6 interviewers per time -> rooms are the bottleneck
    students = []
    for sid in range(1, n_students + 1):
        picks = rng.sample(range(1, n_slots + 1), 3)
        students.append(student(sid, *picks))
    return batch(slots, students)


def assert_no_double_booking(testcase, data, result):
    """Interviewer, room and student never used twice in overlapping windows."""
    by_slot = {s["slotId"]: s for s in data["slots"]}
    seen_students = set()
    used = []
    for a in result["assignments"]:
        testcase.assertNotIn(a["studentId"], seen_students)
        seen_students.add(a["studentId"])
        s = by_slot[a["slotId"]]
        used.append((s["start"], s["end"], tuple(a["interviewerIds"]), a["roomId"], a["slotId"]))
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            a, b = used[i], used[j]
            testcase.assertNotEqual(a[4], b[4], "slot used twice")
            if a[0] < b[1] and b[0] < a[1]:
                testcase.assertFalse(set(a[2]) & set(b[2]), f"interviewer double-booked {a} {b}")
                if a[3] is not None:
                    testcase.assertNotEqual(a[3], b[3], f"room double-booked {a} {b}")
