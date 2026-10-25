"""Data models and input validation for the scheduler package (Section 4.4).

Pure Python: no DB / HTTP / Redis imports. All parsing errors raise ValueError
with a message that says which field is wrong.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SLOT_MINUTES = 30

DEFAULT_WEIGHTS = {"rank1": 100, "rank2": 60, "rank3": 30, "unmatchedPenalty": 1000}
DEFAULT_MOVE_WEIGHTS = {
    "movePenalty": 500,
    "swapInterviewer": 50,
    "nextRanked": 150,
    "nearestSlot": 300,
}

STRATEGIES = ("SWAP_INTERVIEWER", "NEXT_RANKED", "NEAREST_FREE", "UNRESOLVED")
REASONS = ("ALL_PREFERRED_SLOTS_TAKEN", "NO_PREFERENCES", "NO_FEASIBLE_SLOT")


# ---------------------------------------------------------------- time helpers
def parse_ts(value: Any, field: str = "timestamp") -> datetime:
    """Parse an ISO-8601 string (e.g. 2026-11-03T09:00:00Z) to an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected ISO-8601 string, got {value!r}")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{field}: invalid ISO-8601 time {value!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def overlap_cliques(items: Sequence[Tuple[Any, datetime, datetime]]) -> List[Tuple[Any, ...]]:
    """Sweep-line: for every distinct start time return the set of keys whose
    interval contains that instant. Only sets with >= 2 keys are returned.
    Interval graphs are perfect, so "at most one per clique" is exactly
    "no two overlapping" - without O(n^2) pairwise constraints."""
    seen = set()
    out: List[Tuple[Any, ...]] = []
    for _, t, _e in sorted(items, key=lambda it: it[1]):
        members = tuple(sorted(k for k, s, e in items if s <= t < e))
        if len(members) > 1 and members not in seen:
            seen.add(members)
            out.append(members)
    return out


# --------------------------------------------------------------- validation
def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field}: expected integer, got {value!r}")
    return value


def _num(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected number, got {value!r}")
    return int(round(value))


def _list(value: Any, field: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field}: expected list, got {type(value).__name__}")
    return value


def _dict(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected object, got {type(value).__name__}")
    return value


def _tags(value: Any, field: str) -> Tuple[str, ...]:
    out = []
    for t in _list(value, field):
        if not isinstance(t, str):
            raise ValueError(f"{field}: skill tags must be strings, got {t!r}")
        out.append(t)
    return tuple(out)


# -------------------------------------------------------------------- models
@dataclass(frozen=True)
class SlotIn:
    slot_id: int
    interviewer_ids: Tuple[int, ...]
    start: datetime
    end: datetime
    room_id: Optional[int]
    skill_tags: Tuple[str, ...]
    # stretch: ((interviewerId, skillTags), ...) for panel slots
    panel: Tuple[Tuple[int, Tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class PrefIn:
    slot_id: int
    rank: int


@dataclass(frozen=True)
class StudentIn:
    student_id: int
    prefs: Tuple[PrefIn, ...]


@dataclass(frozen=True)
class Assignment:
    student_id: int
    slot_id: int
    rank_got: int
    interviewer_ids: Tuple[int, ...]
    room_id: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "studentId": self.student_id,
            "slotId": self.slot_id,
            "rankGot": self.rank_got,
            "interviewerIds": list(self.interviewer_ids),
            "roomId": self.room_id,
        }


@dataclass(frozen=True)
class BatchInput:
    round_no: int
    slots: Tuple[SlotIn, ...]
    rooms: frozenset
    students: Tuple[StudentIn, ...]
    company_id: Optional[int]
    required_skills: Tuple[str, ...]
    weights: Dict[str, int]


@dataclass(frozen=True)
class CurrentInterview:
    interview_id: int
    student_id: int
    slot_id: int
    interviewer_ids: Tuple[int, ...]
    room_id: Optional[int]
    round_no: Optional[int]


@dataclass(frozen=True)
class RescheduleInput:
    batch: BatchInput
    current: Tuple[CurrentInterview, ...]
    cancelled_interviewer_id: Optional[int]
    cancelled_slot_ids: Tuple[int, ...]
    free_slots: Tuple[SlotIn, ...]
    move_weights: Dict[str, int]


def parse_slot(raw: Any, field: str = "slot") -> SlotIn:
    raw = _dict(raw, field)
    slot_id = _int(raw.get("slotId"), f"{field}.slotId")
    if raw.get("interviewerIds") is not None:
        ids = tuple(_int(i, f"{field}.interviewerIds") for i in _list(raw["interviewerIds"], field))
    elif raw.get("interviewerId") is not None:
        ids = (_int(raw["interviewerId"], f"{field}.interviewerId"),)
    else:
        raise ValueError(f"{field} {slot_id}: needs interviewerId or interviewerIds")
    if not ids:
        raise ValueError(f"{field} {slot_id}: interviewerIds is empty")
    start = parse_ts(raw.get("start"), f"{field} {slot_id}.start")
    end = parse_ts(raw.get("end"), f"{field} {slot_id}.end")
    if not start < end:
        raise ValueError(f"{field} {slot_id}: start must be before end")
    room = raw.get("roomId")
    room = None if room is None else _int(room, f"{field} {slot_id}.roomId")
    tags = _tags(raw.get("skillTags"), f"{field} {slot_id}.skillTags")
    panel = []
    for m in _list(raw.get("panel"), f"{field} {slot_id}.panel"):
        m = _dict(m, f"{field} {slot_id}.panel[]")
        panel.append((_int(m.get("interviewerId"), "panel.interviewerId"),
                      _tags(m.get("skillTags"), "panel.skillTags")))
    return SlotIn(slot_id, ids, start, end, room, tags, tuple(panel))


def _parse_slots(raw: Any, field: str) -> Tuple[SlotIn, ...]:
    slots = [parse_slot(s, field) for s in _list(raw, field)]
    ids = [s.slot_id for s in slots]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field}: duplicate slotId")
    return tuple(slots)


def _parse_weights(raw: Any, defaults: Dict[str, int], field: str) -> Dict[str, int]:
    out = dict(defaults)
    if raw is not None:
        for k, v in _dict(raw, field).items():
            out[k] = _num(v, f"{field}.{k}")
    return out


def parse_input(data: Any) -> BatchInput:
    """Validate and convert a solve_batch input dict. Raises ValueError."""
    data = _dict(data, "input")
    round_no = _int(data.get("roundNo", 1), "roundNo")
    if round_no not in (1, 2, 3):
        raise ValueError(f"roundNo: must be 1, 2 or 3, got {round_no}")
    slots = _parse_slots(data.get("slots"), "slots")
    rooms = []
    for r in _list(data.get("rooms"), "rooms"):
        rooms.append(_int(_dict(r, "rooms[]").get("roomId"), "rooms[].roomId"))
    students = []
    seen = set()
    for raw in _list(data.get("students"), "students"):
        raw = _dict(raw, "students[]")
        sid = _int(raw.get("studentId"), "students[].studentId")
        if sid in seen:
            raise ValueError(f"students: duplicate studentId {sid}")
        seen.add(sid)
        prefs, ranks, pslots = [], set(), set()
        for p in _list(raw.get("prefs"), f"student {sid}.prefs"):
            p = _dict(p, f"student {sid}.prefs[]")
            slot_id = _int(p.get("slotId"), f"student {sid}.prefs[].slotId")
            rank = _int(p.get("rank"), f"student {sid}.prefs[].rank")
            if rank not in (1, 2, 3):
                raise ValueError(f"student {sid}: rank must be 1..3, got {rank}")
            if rank in ranks:
                raise ValueError(f"student {sid}: duplicate rank {rank}")
            if slot_id in pslots:
                raise ValueError(f"student {sid}: slot {slot_id} ranked twice")
            ranks.add(rank)
            pslots.add(slot_id)
            prefs.append(PrefIn(slot_id, rank))
        students.append(StudentIn(sid, tuple(sorted(prefs, key=lambda p: p.rank))))
    pr = data.get("panelRequirements") or {}
    pr = _dict(pr, "panelRequirements")
    company = pr.get("companyId")
    company = None if company is None else _int(company, "panelRequirements.companyId")
    required = _tags(pr.get("requiredSkills"), "panelRequirements.requiredSkills")
    weights = _parse_weights(data.get("weights"), DEFAULT_WEIGHTS, "weights")
    return BatchInput(round_no, slots, frozenset(rooms), tuple(students), company, required, weights)


def parse_reschedule_input(data: Any) -> RescheduleInput:
    data = _dict(data, "input")
    batch = parse_input(data)
    current = []
    seen = set()
    for raw in _list(data.get("currentInterviews"), "currentInterviews"):
        raw = _dict(raw, "currentInterviews[]")
        iid = _int(raw.get("interviewId"), "currentInterviews[].interviewId")
        if iid in seen:
            raise ValueError(f"currentInterviews: duplicate interviewId {iid}")
        seen.add(iid)
        ivs = tuple(_int(i, "currentInterviews[].interviewerIds")
                    for i in _list(raw.get("interviewerIds"), "currentInterviews[].interviewerIds"))
        room = raw.get("roomId")
        rn = raw.get("roundNo")
        current.append(CurrentInterview(
            iid,
            _int(raw.get("studentId"), "currentInterviews[].studentId"),
            _int(raw.get("slotId"), "currentInterviews[].slotId"),
            ivs,
            None if room is None else _int(room, "currentInterviews[].roomId"),
            None if rn is None else _int(rn, "currentInterviews[].roundNo"),
        ))
    canc = _dict(data.get("cancelled") or {}, "cancelled")
    cid = canc.get("interviewerId")
    cid = None if cid is None else _int(cid, "cancelled.interviewerId")
    cslots = tuple(_int(s, "cancelled.slotIds") for s in _list(canc.get("slotIds"), "cancelled.slotIds"))
    if cid is None and not cslots and current:
        raise ValueError("cancelled: needs interviewerId and/or slotIds")
    free = _parse_slots(data.get("freeSlots"), "freeSlots")
    mw = _parse_weights(data.get("moveWeights"), DEFAULT_MOVE_WEIGHTS, "moveWeights")
    return RescheduleInput(batch, tuple(current), cid, cslots, free, mw)
