"""Batch interview matching with OR-Tools CP-SAT (Section 4.4).

Model
  x[s, slot]  Boolean, created ONLY for (student, slot) pairs the student ranked
              and that are usable (slot exists, room valid, required skills covered).
  matched[s]  = sum_slot x[s, slot]          (C1: each student <= 1 slot)
  used[slot]  = sum_s   x[s, slot]           (C2: each slot  <= 1 student)
  C3/C4       per interviewer and per room: at most one used slot per time
              window (overlapping slots conflict) - encoded as AtMostOne over
              sweep-line cliques, not pairwise.
  C6          if panelRequirements.requiredSkills is non-empty, a slot must
              cover all of them (union of its panel's skill tags).
  Objective   maximise sum weight(rank)*x + unmatchedPenalty*sum(matched)
              (= sum weight*x - unmatchedPenalty*unmatched + constant), so one
              extra matched student always beats any rank improvement.

Determinism
  Input is sorted by id, a fixed random seed and ONE search worker are used,
  and a tiny lexicographic tie-break prefers lower studentId / lower slotId.
  The result therefore does not depend on submission order.

Size / complexity
  Variables = number of ranked (student, slot) pairs <= 3 * students, plus one
  Boolean per student and per ranked slot. Constraints: one per student, one per
  slot, and one per overlap clique (<= number of slots per interviewer / room).
  Nothing is created for unranked pairs, so 200 students x 60 slots is tiny.
"""
import time
from typing import Any, Dict, List

from ortools.sat.python import cp_model

from .models import (BatchInput, Assignment, overlap_cliques, parse_input)


def _configure(solver: "cp_model.CpSolver", time_limit_sec: float) -> None:
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.random_seed = 12345
    if hasattr(solver.parameters, "num_workers"):
        solver.parameters.num_workers = 1
    else:  # older OR-Tools
        solver.parameters.num_search_workers = 1


def _usable_slots(inp: BatchInput) -> Dict[int, Any]:
    """Slots that can host an interview at all (room valid, skills covered)."""
    usable = {}
    required = set(inp.required_skills)
    for s in inp.slots:
        if s.room_id is not None and inp.rooms and s.room_id not in inp.rooms:
            continue
        if required:
            have = set(s.skill_tags)
            for _, tags in s.panel:
                have.update(tags)
            if not required <= have:
                continue
        usable[s.slot_id] = s
    return usable


def _unmatched_entry(student, has_vars: bool) -> Dict[str, Any]:
    if not student.prefs:
        reason = "NO_PREFERENCES"
    elif not has_vars:
        reason = "NO_FEASIBLE_SLOT"
    else:
        reason = "ALL_PREFERRED_SLOTS_TAKEN"
    return {"studentId": student.student_id, "reason": reason}


def _result(status: str, inp: BatchInput, assigned: List[Assignment],
            unmatched: List[Dict[str, Any]], t0: float) -> Dict[str, Any]:
    w = inp.weights
    wt = {1: w["rank1"], 2: w["rank2"], 3: w["rank3"]}
    ranks = {1: 0, 2: 0, 3: 0}
    obj = 0
    for a in assigned:
        ranks[a.rank_got] += 1
        obj += wt[a.rank_got]
    obj -= w["unmatchedPenalty"] * len(unmatched)
    return {
        "status": status,
        "objectiveValue": obj,
        "assignments": [a.to_dict() for a in sorted(assigned, key=lambda a: a.student_id)],
        "unmatched": sorted(unmatched, key=lambda u: u["studentId"]),
        "stats": {
            "matched": len(assigned),
            "unmatched": len(unmatched),
            "rank1": ranks[1],
            "rank2": ranks[2],
            "rank3": ranks[3],
            "wallTimeSec": round(time.time() - t0, 3),
        },
    }


def solve_batch(data: dict, time_limit_sec: int = 20) -> dict:
    t0 = time.time()
    inp = parse_input(data)
    w = inp.weights
    rank_w = {1: w["rank1"], 2: w["rank2"], 3: w["rank3"]}

    students = sorted(inp.students, key=lambda s: s.student_id)
    slots = sorted(_usable_slots(inp).values(), key=lambda s: s.slot_id)
    slot_by_id = {s.slot_id: s for s in slots}
    slot_idx = {s.slot_id: i for i, s in enumerate(slots)}

    model = cp_model.CpModel()
    x: Dict[tuple, Any] = {}
    by_student: Dict[int, list] = {}
    by_slot: Dict[int, list] = {}
    for st in students:
        for p in st.prefs:
            if p.slot_id in slot_by_id:
                v = model.NewBoolVar(f"x_{st.student_id}_{p.slot_id}")
                x[(st.student_id, p.slot_id)] = v
                by_student.setdefault(st.student_id, []).append((v, p.rank))
                by_slot.setdefault(p.slot_id, []).append(v)

    if not x:  # nothing to solve
        unmatched = [_unmatched_entry(st, False) for st in students]
        return _result("OPTIMAL", inp, [], unmatched, t0)

    # C1: student <= 1 slot
    matched = {}
    for sid, items in by_student.items():
        m = model.NewBoolVar(f"matched_{sid}")
        model.Add(sum(v for v, _ in items) == m)
        matched[sid] = m

    # C2: slot <= 1 student
    used = {}
    for slot_id, vs in by_slot.items():
        u = model.NewBoolVar(f"used_{slot_id}")
        model.Add(sum(vs) == u)
        used[slot_id] = u

    # C3 / C4: no overlapping use of the same interviewer or room
    per_interviewer: Dict[int, list] = {}
    per_room: Dict[int, list] = {}
    for slot_id in used:
        s = slot_by_id[slot_id]
        for iid in s.interviewer_ids:
            per_interviewer.setdefault(iid, []).append((slot_id, s.start, s.end))
        if s.room_id is not None:
            per_room.setdefault(s.room_id, []).append((slot_id, s.start, s.end))
    for groups in (per_interviewer, per_room):
        for _, items in sorted(groups.items()):
            for clique in overlap_cliques(items):
                model.AddAtMostOne(used[k] for k in clique)

    # Objective (primary) + lexicographic tie-break (lower studentId / slotId first)
    n_s, n_sl = len(students), len(slots)
    sidx = {st.student_id: i for i, st in enumerate(students)}
    tb = {}
    for (sid, slot_id) in x:
        tb[(sid, slot_id)] = (n_s - sidx[sid]) * (n_sl + 1) + (n_sl - slot_idx[slot_id])
    big = sum(tb.values()) + 1
    primary = sum(rank_w[r] * v for items in by_student.values() for v, r in items) \
        + w["unmatchedPenalty"] * sum(matched.values())
    model.Maximize(big * primary + sum(tb[k] * v for k, v in x.items()))

    solver = cp_model.CpSolver()
    _configure(solver, time_limit_sec)
    status = solver.Solve(model)

    has_vars = {sid: True for sid in by_student}
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Fallback: everyone unmatched, backend shows "no slot fits, choose new slots"
        unmatched = [_unmatched_entry(st, st.student_id in has_vars) for st in students]
        return _result("INFEASIBLE", inp, [], unmatched, t0)

    assigned: List[Assignment] = []
    unmatched: List[Dict[str, Any]] = []
    rank_of = {(st.student_id, p.slot_id): p.rank for st in students for p in st.prefs}
    for st in students:
        got = None
        for p in st.prefs:
            v = x.get((st.student_id, p.slot_id))
            if v is not None and solver.Value(v):
                got = p
                break
        if got is None:
            unmatched.append(_unmatched_entry(st, st.student_id in has_vars))
        else:
            s = slot_by_id[got.slot_id]
            assigned.append(Assignment(st.student_id, got.slot_id,
                                       rank_of[(st.student_id, got.slot_id)],
                                       s.interviewer_ids, s.room_id))
    name = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
    return _result(name, inp, assigned, unmatched, t0)
