"""Minimal-change schedule repair after an interviewer cancels (Section 4.4).

Input = solve_batch input plus currentInterviews / cancelled / freeSlots /
moveWeights. `slots` is the slot universe (needed to know the time and room of
every current interview); `freeSlots` are the slots that may be used as new homes.

Rules
  * Interviews not on a cancelled slot are frozen (untouched) and block their
    interviewers / rooms for the whole time window.
  * Each affected interview gets candidate repairs, cheapest first:
      SWAP_INTERVIEWER  another interviewer free in the SAME time window with an
                        overlapping skill tag (panels: replace_panelist)
      NEXT_RANKED       one of the student's other ranked free slots
      NEAREST_FREE      the free slots nearest in time (closest 25 considered)
  * CP-SAT picks one option (or "unresolved") per affected interview minimising
      sum(strategy cost + movePenalty) + big penalty per unresolved
    under the same no-double-booking rules as the batch model.

Size: options per affected interview <= ~30, so the model is tiny.
"""
from typing import Any, Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from .models import (SLOT_MINUTES, SlotIn, overlap_cliques, overlaps,
                     parse_reschedule_input)
from .panel import replace_panelist

UNRESOLVED_PENALTY = 1_000_000
NEAREST_LIMIT = 25
_ORDER = {"SWAP_INTERVIEWER": 0, "NEXT_RANKED": 1, "NEAREST_FREE": 2}


class _Option:
    __slots__ = ("to_slot", "interviewers", "room", "start", "end", "strategy", "cost")

    def __init__(self, to_slot, interviewers, room, start, end, strategy, cost):
        self.to_slot, self.interviewers, self.room = to_slot, tuple(interviewers), room
        self.start, self.end, self.strategy, self.cost = start, end, strategy, cost


def _tags_overlap(a: Tuple[str, ...], b: Tuple[str, ...]) -> bool:
    return not a or bool(set(a) & set(b))


def reschedule(data: dict, time_limit_sec: int = 10) -> dict:
    inp = parse_reschedule_input(data)
    batch, mw = inp.batch, inp.move_weights
    cid = inp.cancelled_interviewer_id
    cslots = set(inp.cancelled_slot_ids)

    lookup: Dict[int, SlotIn] = {s.slot_id: s for s in batch.slots}
    lookup.update({s.slot_id: s for s in inp.free_slots})

    interviews = sorted(inp.current, key=lambda i: i.interview_id)

    def affected(iv) -> bool:
        if cslots:
            return iv.slot_id in cslots
        return cid in iv.interviewer_ids

    hit = [iv for iv in interviews if affected(iv)]
    frozen = [iv for iv in interviews if not affected(iv)]
    if not hit:
        return {"status": "OPTIMAL", "moves": [], "untouched": len(frozen), "unresolved": []}

    frozen_slots = {iv.slot_id for iv in frozen}
    reservations = []  # (interviewer ids, room, start, end)
    for iv in frozen:
        s = lookup.get(iv.slot_id)
        if s is not None:
            reservations.append((iv.interviewer_ids, iv.room_id, s.start, s.end))

    def room_ok(s: SlotIn) -> bool:
        return s.room_id is None or not batch.rooms or s.room_id in batch.rooms

    free = sorted((f for f in inp.free_slots
                   if (cid is None or cid not in f.interviewer_ids)
                   and f.slot_id not in cslots and f.slot_id not in frozen_slots
                   and room_ok(f)), key=lambda f: f.slot_id)
    free_by_id = {f.slot_id: f for f in free}
    prefs_of = {st.student_id: st.prefs for st in batch.students}

    def clashes_frozen(o: _Option) -> bool:
        for ivs, room, s, e in reservations:
            if not overlaps(o.start, o.end, s, e):
                continue
            if set(ivs) & set(o.interviewers):
                return True
            if o.room is not None and room is not None and o.room == room:
                return True
        return False

    def make_options(iv) -> List[_Option]:
        cur = lookup.get(iv.slot_id)
        found: Dict[tuple, _Option] = {}

        def add(o: _Option):
            if clashes_frozen(o):
                return
            key = (o.to_slot, o.interviewers)
            old = found.get(key)
            if old is None or (o.cost, _ORDER[o.strategy]) < (old.cost, _ORDER[old.strategy]):
                found[key] = o

        base = mw["movePenalty"]
        if cur is not None:
            same_time = [f for f in free if f.start == cur.start and f.end == cur.end]
            if len(iv.interviewer_ids) > 1:  # panel: replace just the cancelled member
                panel = [{"interviewerId": i, "skillTags": list(t)} for i, t in cur.panel]
                gone = [p for p in panel if p["interviewerId"] == cid]
                rest = [p for p in panel if p["interviewerId"] != cid]
                if gone or not panel:
                    covered = {t for p in rest for t in p["skillTags"]}
                    need = [t for p in gone for t in p["skillTags"] if t not in covered]
                    cands = [{"interviewerId": f.interviewer_ids[0], "skillTags": list(f.skill_tags),
                              "slotId": f.slot_id}
                             for f in same_time if len(f.interviewer_ids) == 1
                             and f.interviewer_ids[0] not in iv.interviewer_ids]
                    best = replace_panelist(rest, need, cands)
                    if best is not None:
                        new_ids = [i for i in iv.interviewer_ids if i != cid] + [best["interviewerId"]]
                        add(_Option(iv.slot_id, new_ids, iv.room_id, cur.start, cur.end,
                                    "SWAP_INTERVIEWER", mw["swapInterviewer"] + base))
            else:
                for f in same_time:
                    if _tags_overlap(cur.skill_tags, f.skill_tags):
                        add(_Option(f.slot_id, f.interviewer_ids, f.room_id, f.start, f.end,
                                    "SWAP_INTERVIEWER", mw["swapInterviewer"] + base))
        for p in prefs_of.get(iv.student_id, ()):
            f = free_by_id.get(p.slot_id)
            if f is not None and p.slot_id != iv.slot_id:
                add(_Option(f.slot_id, f.interviewer_ids, f.room_id, f.start, f.end,
                            "NEXT_RANKED", mw["nextRanked"] + p.rank + base))
        if cur is not None:
            def dist(f):
                return abs((f.start - cur.start).total_seconds()) / 60.0 / SLOT_MINUTES
            for f in sorted(free, key=lambda f: (dist(f), f.slot_id))[:NEAREST_LIMIT]:
                add(_Option(f.slot_id, f.interviewer_ids, f.room_id, f.start, f.end,
                            "NEAREST_FREE", mw["nearestSlot"] + min(int(dist(f)), 99) + base))
        return sorted(found.values(), key=lambda o: (o.cost, _ORDER[o.strategy], o.to_slot, o.interviewers))

    model = cp_model.CpModel()
    opts: Dict[int, List[_Option]] = {}
    zvars: Dict[int, list] = {}
    unres: Dict[int, Any] = {}
    terms = []
    by_interviewer: Dict[int, list] = {}
    by_room: Dict[int, list] = {}
    for iv in hit:
        opts[iv.interview_id] = make_options(iv)
        zs = []
        for k, o in enumerate(opts[iv.interview_id]):
            z = model.NewBoolVar(f"z_{iv.interview_id}_{k}")
            zs.append(z)
            terms.append((o.cost * 1000 + min(k, 999)) * z)
            key = (iv.interview_id, k)
            for i in o.interviewers:
                by_interviewer.setdefault(i, []).append((key, o.start, o.end))
            if o.room is not None:
                by_room.setdefault(o.room, []).append((key, o.start, o.end))
        u = model.NewBoolVar(f"unres_{iv.interview_id}")
        unres[iv.interview_id] = u
        zvars[iv.interview_id] = zs
        model.AddExactlyOne(zs + [u])
        terms.append(UNRESOLVED_PENALTY * 1000 * u)
    for groups in (by_interviewer, by_room):
        for _, items in sorted(groups.items()):
            for clique in overlap_cliques(items):
                model.AddAtMostOne(zvars[a][b] for a, b in clique)
    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.random_seed = 12345
    if hasattr(solver.parameters, "num_workers"):
        solver.parameters.num_workers = 1
    else:
        solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    ok = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    moves, unresolved = [], []
    for iv in hit:
        chosen: Optional[_Option] = None
        if ok:
            for k, z in enumerate(zvars[iv.interview_id]):
                if solver.Value(z):
                    chosen = opts[iv.interview_id][k]
                    break
        if chosen is None:
            unresolved.append(iv.student_id)
            moves.append({"interviewId": iv.interview_id, "studentId": iv.student_id,
                          "fromSlotId": iv.slot_id, "toSlotId": None,
                          "strategy": "UNRESOLVED", "newInterviewerIds": []})
        else:
            moves.append({"interviewId": iv.interview_id, "studentId": iv.student_id,
                          "fromSlotId": iv.slot_id, "toSlotId": chosen.to_slot,
                          "strategy": chosen.strategy,
                          "newInterviewerIds": list(chosen.interviewers)})
    if not ok:
        name = "INFEASIBLE"
    else:
        name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    return {"status": name, "moves": moves, "untouched": len(frozen),
            "unresolved": sorted(unresolved)}
