import copy
import json
import random
import unittest

import _util as u
from scheduler import solve_batch


def strip(result):
    r = copy.deepcopy(result)
    r["stats"].pop("wallTimeSec", None)
    return r


class SolveBatchTests(unittest.TestCase):
    def test_no_double_booking_interviewer_room_student(self):
        # slots 1 & 2: same interviewer, overlapping; slots 3 & 4: different interviewers, same room+time
        slots = [u.slot(1, 7, 0, room_id=1), u.slot(2, 7, 15, room_id=2),
                 u.slot(3, 8, 60, room_id=3), u.slot(4, 9, 60, room_id=3)]
        studs = [u.student(1, 1, 3), u.student(2, 2, 4), u.student(3, 1, 2), u.student(4, 3, 4)]
        data = u.batch(slots, studs)
        res = solve_batch(data)
        u.assert_no_double_booking(self, data, res)
        self.assertEqual(res["stats"]["matched"], 2)  # only 2 non-conflicting windows

    def test_rank_preference_respected_when_no_conflict(self):
        slots = [u.slot(1, 7, 0), u.slot(2, 7, 30), u.slot(3, 7, 60)]
        data = u.batch(slots, [u.student(1, 2, 1, 3)])
        res = solve_batch(data)
        self.assertEqual(res["assignments"][0]["slotId"], 2)
        self.assertEqual(res["assignments"][0]["rankGot"], 1)
        self.assertEqual(res["objectiveValue"], 100)
        self.assertEqual(res["status"], "OPTIMAL")

    def test_global_optimum_beats_first_come(self):
        # Greedy would give slot 1 to student 1 and leave student 2 with nothing.
        slots = [u.slot(1, 7, 0), u.slot(2, 8, 30, room_id=2)]
        data = u.batch(slots, [u.student(1, 1, 2), u.student(2, 1)])
        res = solve_batch(data)
        got = {a["studentId"]: a["slotId"] for a in res["assignments"]}
        self.assertEqual(got, {1: 2, 2: 1})
        self.assertEqual(res["unmatched"], [])
        self.assertEqual(res["objectiveValue"], 100 + 60)

    def test_matching_beats_rank_improvement(self):
        # Two students want slot 1; student 2 has a rank-3 fallback. Both matched is better.
        slots = [u.slot(1, 7, 0), u.slot(2, 8, 0, room_id=2), u.slot(3, 9, 0, room_id=3)]
        data = u.batch(slots, [u.student(1, 1), u.student(2, 1, 2, 3)])
        res = solve_batch(data)
        self.assertEqual(res["stats"]["matched"], 2)

    def test_order_independent(self):
        data = u.big_scenario(40, 20, seed=3)
        base = strip(solve_batch(data))
        rng = random.Random(1)
        for _ in range(3):
            d = copy.deepcopy(data)
            rng.shuffle(d["students"])
            rng.shuffle(d["slots"])
            for s in d["students"]:
                rng.shuffle(s["prefs"])
            self.assertEqual(strip(solve_batch(d)), base)

    def test_unmatched_reasons(self):
        slots = [u.slot(1, 7, 0, room_id=1), u.slot(2, 8, 0, room_id=9)]
        studs = [u.student(1, 1),            # wins slot 1
                 u.student(2, 1),            # loses -> ALL_PREFERRED_SLOTS_TAKEN
                 u.student(3),               # NO_PREFERENCES
                 u.student(4, 99),           # unknown slot -> NO_FEASIBLE_SLOT
                 u.student(5, 2)]            # slot 2 has room 9, not in rooms -> NO_FEASIBLE_SLOT
        data = u.batch(slots, studs, rooms=[1])
        res = solve_batch(data)
        reasons = {x["studentId"]: x["reason"] for x in res["unmatched"]}
        self.assertEqual(reasons, {2: "ALL_PREFERRED_SLOTS_TAKEN", 3: "NO_PREFERENCES",
                                   4: "NO_FEASIBLE_SLOT", 5: "NO_FEASIBLE_SLOT"})
        self.assertEqual([a["studentId"] for a in res["assignments"]], [1])
        self.assertEqual(res["objectiveValue"], 100 - 4 * 1000)

    def test_empty_input_safe(self):
        for data in ({}, {"slots": [], "students": []}, u.batch([], [])):
            res = solve_batch(data)
            self.assertEqual(res["status"], "OPTIMAL")
            self.assertEqual(res["assignments"], [])
            self.assertEqual(res["unmatched"], [])
            self.assertEqual(res["stats"]["matched"], 0)

    def test_students_but_no_slots(self):
        res = solve_batch(u.batch([], [u.student(1, 1), u.student(2)]))
        self.assertEqual({x["studentId"]: x["reason"] for x in res["unmatched"]},
                         {1: "NO_FEASIBLE_SLOT", 2: "NO_PREFERENCES"})

    def test_required_skills_filter_slots(self):
        slots = [u.slot(1, 7, 0, tags=("Coding",)), u.slot(2, 8, 30, tags=("Coding", "Tech"), room_id=2)]
        data = u.batch(slots, [u.student(1, 1, 2)], required=["Tech"])
        res = solve_batch(data)
        self.assertEqual(res["assignments"][0]["slotId"], 2)
        self.assertEqual(res["assignments"][0]["rankGot"], 2)

    def test_output_shape_matches_contract(self):
        res = solve_batch(u.big_scenario(10, 6, seed=1))
        self.assertEqual(set(res), {"status", "objectiveValue", "assignments", "unmatched", "stats"})
        self.assertIn(res["status"], ("OPTIMAL", "FEASIBLE", "INFEASIBLE"))
        self.assertEqual(set(res["stats"]), {"matched", "unmatched", "rank1", "rank2", "rank3", "wallTimeSec"})
        for a in res["assignments"]:
            self.assertEqual(set(a), {"studentId", "slotId", "rankGot", "interviewerIds", "roomId"})
        for x in res["unmatched"]:
            self.assertIn(x["reason"], ("ALL_PREFERRED_SLOTS_TAKEN", "NO_PREFERENCES", "NO_FEASIBLE_SLOT"))
        json.dumps(res)  # JSON-serialisable

    def test_200_students_60_slots_under_time_limit(self):
        data = u.big_scenario(200, 60)
        res = solve_batch(data, time_limit_sec=20)
        self.assertIn(res["status"], ("OPTIMAL", "FEASIBLE"))
        self.assertLess(res["stats"]["wallTimeSec"], 20)
        u.assert_no_double_booking(self, data, res)
        self.assertEqual(res["stats"]["matched"] + res["stats"]["unmatched"], 200)

    def test_bad_input_raises_value_error(self):
        bad = [
            {"slots": [{"slotId": 1, "interviewerId": 7, "start": "nope", "end": "x"}]},
            {"slots": [u.slot(1, 7, 0), u.slot(1, 8, 0)]},                       # duplicate slotId
            {"students": [{"studentId": 1, "prefs": [{"slotId": 1, "rank": 4}]}]},
            {"students": [{"studentId": 1, "prefs": [{"slotId": 1, "rank": 1}, {"slotId": 2, "rank": 1}]}]},
            {"students": [{"studentId": 1}, {"studentId": 1}]},
            {"slots": [dict(u.slot(1, 7, 0), end=u.ts(-30))]},                   # end before start
            [],
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=str(data)[:60]):
                solve_batch(data)

    def test_sample_fixture_matches_published_output(self):
        res = solve_batch(u.load_fixture("sample_input.json"))
        self.assertEqual(strip(res), strip(u.load_fixture("sample_output.json")))


if __name__ == "__main__":
    unittest.main()
