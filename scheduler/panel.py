"""Stretch: panel interviews (all members free + required skill mix covered).

build_panel_slots(data) turns single-interviewer slots into panel slots that
can be fed straight into solve_batch (which already enforces that every member
interviewer is free, that the room is unique, and that required skills are
covered). replace_panelist() picks a substitute with the right skill and is
used by reschedule() for the SWAP_INTERVIEWER strategy on panels.

Complexity: grouping is O(n log n); the greedy cover per time window is
O(k^2 * s) for k slots in the window and s required skills (both tiny).
"""
import copy
from typing import Any, Dict, Iterable, List, Optional, Union

from .models import format_ts, parse_input


def _skill_set(skill: Union[str, Iterable[str], None]) -> set:
    if skill is None:
        return set()
    if isinstance(skill, str):
        return {skill}
    return set(skill)


def replace_panelist(panel: List[Dict[str, Any]], skill: Union[str, Iterable[str], None],
                     candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best substitute for a panelist.

    panel:      [{"interviewerId", "skillTags"}] - the members that stay
    skill:      skill (or list of skills) the substitute must have
    candidates: [{"interviewerId", "skillTags", ...}]
    Returns the candidate dict (unchanged) or None. Best = has every needed
    skill, is not already on the panel, fewest unrelated tags (specialist),
    then lowest interviewerId (deterministic).
    """
    need = _skill_set(skill)
    on_panel = {m["interviewerId"] for m in panel}
    best, best_key = None, None
    for c in candidates:
        if c["interviewerId"] in on_panel:
            continue
        tags = set(c.get("skillTags") or [])
        if not need <= tags:
            continue
        key = (len(tags - need), c["interviewerId"])
        if best_key is None or key < best_key:
            best, best_key = c, key
    return best


def build_panel_slots(data: dict) -> dict:
    """Return a copy of a solve_batch input whose slots are panel slots.

    * With no requiredSkills every slot stays a panel of one (data unchanged).
    * Otherwise slots sharing the same (start, end, roomId) are merged: a greedy
      set cover picks members until all required skills are covered; leftovers
      form further panels while possible. Panel slotId = smallest member slotId.
    * Student prefs that pointed at any member slot are remapped to the panel
      slot (best rank kept, duplicates removed).
    """
    inp = parse_input(data)  # validates
    out = copy.deepcopy(data)
    required = set(inp.required_skills)
    if not required:
        return out

    groups: Dict[tuple, list] = {}
    for s in sorted(inp.slots, key=lambda s: s.slot_id):
        groups.setdefault((s.start, s.end, s.room_id), []).append(s)

    panels, remap = [], {}
    for (start, end, room), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        pool = [m for m in members if len(m.interviewer_ids) == 1]
        while pool:
            chosen, missing = [], set(required)
            remaining = list(pool)
            while missing and remaining:
                remaining.sort(key=lambda m: (-len(missing & set(m.skill_tags)), m.interviewer_ids[0]))
                pick = remaining.pop(0)
                if not missing & set(pick.skill_tags):
                    break
                chosen.append(pick)
                missing -= set(pick.skill_tags)
            if missing or not chosen:
                break
            chosen.sort(key=lambda m: m.slot_id)
            pid = chosen[0].slot_id
            panels.append({
                "slotId": pid,
                "interviewerIds": [m.interviewer_ids[0] for m in chosen],
                "start": format_ts(start), "end": format_ts(end), "roomId": room,
                "skillTags": sorted({t for m in chosen for t in m.skill_tags}),
                "panel": [{"interviewerId": m.interviewer_ids[0], "skillTags": list(m.skill_tags)}
                          for m in chosen],
            })
            for m in chosen:
                remap[m.slot_id] = pid
            ids = {m.slot_id for m in chosen}
            pool = [m for m in pool if m.slot_id not in ids]

    out["slots"] = sorted(panels, key=lambda p: p["slotId"])
    for st in out.get("students", []):
        best: Dict[int, int] = {}
        for p in st.get("prefs", []):
            pid = remap.get(p["slotId"])
            if pid is not None and (pid not in best or p["rank"] < best[pid]):
                best[pid] = p["rank"]
        used_ranks, prefs = set(), []
        for pid, rank in sorted(best.items(), key=lambda kv: kv[1]):
            if rank in used_ranks:  # keep ranks unique after merging
                continue
            used_ranks.add(rank)
            prefs.append({"slotId": pid, "rank": rank})
        st["prefs"] = prefs
    return out
