"""Greedy stand-in for Varnika's CP-SAT scheduler (master prompt section 6).

Same function names and the same 4.4 input/output shapes as `scheduler.solve_batch` /
`scheduler.reschedule`, so swapping is one line (USE_STUB_SOLVER=false).
Pure functions, no I/O. NOT optimal — it is first-come by studentId — but never double-books.
"""
from datetime import datetime

DEFAULT_WEIGHTS = {"rank1": 100, "rank2": 60, "rank3": 30, "unmatchedPenalty": 1000}
DEFAULT_MOVE_WEIGHTS = {"movePenalty": 500, "swapInterviewer": 50, "nextRanked": 150, "nearestSlot": 300}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


class _Busy:
    """Tracks what is already taken so nothing is ever double-booked."""

    def __init__(self):
        self.iv, self.room, self.student = {}, {}, {}

    def conflicts(self, slot, student_id=None) -> bool:
        s, e = _t(slot["start"]), _t(slot["end"])
        for rng in self.iv.get(slot["interviewerId"], []):
            if _overlap(s, e, *rng):
                return True
        if slot.get("roomId") is not None:
            for rng in self.room.get(slot["roomId"], []):
                if _overlap(s, e, *rng):
                    return True
        if student_id is not None:
            for rng in self.student.get(student_id, []):
                if _overlap(s, e, *rng):
                    return True
        return False

    def take(self, slot, student_id):
        rng = (_t(slot["start"]), _t(slot["end"]))
        self.iv.setdefault(slot["interviewerId"], []).append(rng)
        if slot.get("roomId") is not None:
            self.room.setdefault(slot["roomId"], []).append(rng)
        self.student.setdefault(student_id, []).append(rng)


def solve_batch(data: dict, time_limit_sec: int = 20) -> dict:
    w = dict(DEFAULT_WEIGHTS, **(data.get("weights") or {}))
    slots = {s["slotId"]: s for s in data.get("slots", [])}
    busy = _Busy()
    assignments, unmatched = [], []
    stats = {"matched": 0, "unmatched": 0, "rank1": 0, "rank2": 0, "rank3": 0, "wallTimeSec": 0.0}
    objective = 0
    for st in sorted(data.get("students", []), key=lambda x: x["studentId"]):
        prefs = sorted(st.get("prefs", []), key=lambda p: p["rank"])
        if not prefs:
            unmatched.append({"studentId": st["studentId"], "reason": "NO_PREFERENCES"})
            continue
        got = None
        known = [p for p in prefs if p["slotId"] in slots]
        for p in known:
            slot = slots[p["slotId"]]
            if not busy.conflicts(slot, st["studentId"]):
                got = (p, slot)
                break
        if got is None:
            unmatched.append({"studentId": st["studentId"],
                              "reason": "ALL_PREFERRED_SLOTS_TAKEN" if known else "NO_FEASIBLE_SLOT"})
            continue
        p, slot = got
        busy.take(slot, st["studentId"])
        assignments.append({"studentId": st["studentId"], "slotId": slot["slotId"], "rankGot": p["rank"],
                            "interviewerIds": [slot["interviewerId"]], "roomId": slot.get("roomId")})
        objective += w["rank%d" % p["rank"]]
        stats["rank%d" % p["rank"]] += 1
    objective -= w["unmatchedPenalty"] * len(unmatched)
    stats["matched"], stats["unmatched"] = len(assignments), len(unmatched)
    return {"status": "FEASIBLE", "objectiveValue": objective, "assignments": assignments,
            "unmatched": unmatched, "stats": stats}


def reschedule(data: dict, time_limit_sec: int = 10) -> dict:
    slots = {s["slotId"]: s for s in data.get("slots", [])}
    free = {s["slotId"]: s for s in data.get("freeSlots", [])}
    cancelled = data.get("cancelled") or {}
    gone = set(cancelled.get("slotIds", []))
    current = data.get("currentInterviews", [])
    prefs = {s["studentId"]: sorted(s.get("prefs", []), key=lambda p: p["rank"]) for s in data.get("students", [])}

    affected = [c for c in current if c["slotId"] in gone]
    affected_ids = {c["interviewId"] for c in affected}
    busy = _Busy()
    for c in current:                                  # untouched interviews stay frozen
        if c["interviewId"] in affected_ids:
            continue
        slot = slots.get(c["slotId"])
        if slot:
            busy.take(slot, c["studentId"])

    moves, unresolved = [], []
    for c in sorted(affected, key=lambda x: x["interviewId"]):
        old = slots.get(c["slotId"])
        choice = None
        # 1. SWAP_INTERVIEWER: same time, another interviewer with overlapping skill tags
        if old:
            for sid, s in sorted(free.items()):
                if s["start"] == old["start"] and s["end"] == old["end"] and s["interviewerId"] != cancelled.get("interviewerId") \
                        and set(s.get("skillTags", [])) & set(old.get("skillTags", [])) \
                        and sid not in gone and not busy.conflicts(s, c["studentId"]):
                    choice = ("SWAP_INTERVIEWER", s)
                    break
        # 2. NEXT_RANKED: the student's other ranked free slot
        if choice is None:
            for p in prefs.get(c["studentId"], []):
                s = free.get(p["slotId"])
                if s and p["slotId"] not in gone and not busy.conflicts(s, c["studentId"]):
                    choice = ("NEXT_RANKED", s)
                    break
        # 3. NEAREST_FREE: free slot closest in time
        if choice is None and old:
            ref = _t(old["start"])
            cands = sorted((abs((_t(s["start"]) - ref).total_seconds()), sid) for sid, s in free.items()
                           if sid not in gone and not busy.conflicts(s, c["studentId"]))
            if cands:
                choice = ("NEAREST_FREE", free[cands[0][1]])
        if choice is None:
            moves.append({"interviewId": c["interviewId"], "studentId": c["studentId"], "fromSlotId": c["slotId"],
                          "toSlotId": None, "strategy": "UNRESOLVED", "newInterviewerIds": []})
            unresolved.append(c["studentId"])
            continue
        strategy, slot = choice
        busy.take(slot, c["studentId"])
        free.pop(slot["slotId"], None)
        moves.append({"interviewId": c["interviewId"], "studentId": c["studentId"], "fromSlotId": c["slotId"],
                      "toSlotId": slot["slotId"], "strategy": strategy, "newInterviewerIds": [slot["interviewerId"]]})
    return {"status": "FEASIBLE", "moves": moves, "untouched": len(current) - len(affected), "unresolved": unresolved}
