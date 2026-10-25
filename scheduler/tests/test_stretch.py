import unittest

import _util as u
from scheduler import (aggregate_ranking, build_panel_slots, eligible_for_next_round,
                       next_round, release_time, reschedule, replace_panelist, solve_batch)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.slots = [u.slot(1, 7, 0, tags=("Coding",)), u.slot(2, 8, 0, tags=("Tech",)),
                      u.slot(3, 9, 0, tags=("HR",)), u.slot(4, 7, 60, tags=("Coding",))]
        self.data = u.batch(self.slots, [u.student(1, 1, 4), u.student(2, 2)], rooms=[1], required=["Coding", "Tech"])

    def test_build_panel_slots_merges_and_remaps(self):
        out = build_panel_slots(self.data)
        self.assertEqual(len(out["slots"]), 1)  # slot 4 has only Coding -> no panel
        p = out["slots"][0]
        self.assertEqual(p["slotId"], 1)
        self.assertEqual(p["interviewerIds"], [7, 8])
        self.assertEqual({s["studentId"]: [x["slotId"] for x in s["prefs"]] for s in out["students"]},
                         {1: [1], 2: [1]})

    def test_no_required_skills_is_unchanged(self):
        d = u.batch(self.slots, [u.student(1, 1)])
        self.assertEqual(build_panel_slots(d), d)

    def test_solver_books_all_panel_members(self):
        res = solve_batch(build_panel_slots(self.data))
        self.assertEqual(res["assignments"][0]["interviewerIds"], [7, 8])
        self.assertEqual(res["stats"]["matched"], 1)

    def test_replace_panelist(self):
        cands = [{"interviewerId": 20, "skillTags": ["Tech", "HR"]},
                 {"interviewerId": 21, "skillTags": ["Tech"]},
                 {"interviewerId": 8, "skillTags": ["Tech"]},
                 {"interviewerId": 22, "skillTags": ["Coding"]}]
        panel = [{"interviewerId": 8, "skillTags": ["Tech"]}, {"interviewerId": 7, "skillTags": ["Coding"]}]
        self.assertEqual(replace_panelist(panel, "Tech", cands)["interviewerId"], 21)
        self.assertIsNone(replace_panelist(panel, "Aptitude", cands))

    def test_reschedule_panel_swap(self):
        panel_slot = {"slotId": 1, "interviewerIds": [7, 8], "start": u.ts(0), "end": u.ts(30), "roomId": 1,
                      "skillTags": ["Coding", "Tech"],
                      "panel": [{"interviewerId": 7, "skillTags": ["Coding"]},
                                {"interviewerId": 8, "skillTags": ["Tech"]}]}
        free = [u.slot(9, 12, 0, room_id=2, tags=("Tech",))]
        data = {"roundNo": 1, "slots": [panel_slot], "rooms": [{"roomId": 1}, {"roomId": 2}],
                "students": [u.student(1, 1)],
                "currentInterviews": [{"interviewId": 5, "studentId": 1, "slotId": 1,
                                       "interviewerIds": [7, 8], "roomId": 1, "roundNo": 1}],
                "cancelled": {"interviewerId": 8, "slotIds": [1]}, "freeSlots": free}
        mv = reschedule(data)["moves"][0]
        self.assertEqual(mv["strategy"], "SWAP_INTERVIEWER")
        self.assertEqual(sorted(mv["newInterviewerIds"]), [7, 12])


class PipelineTests(unittest.TestCase):
    def test_eligibility(self):
        self.assertTrue(eligible_for_next_round([], 1))
        self.assertFalse(eligible_for_next_round([], 2))
        self.assertTrue(eligible_for_next_round([{"roundNo": 1, "verdict": "PASS"}], 2))
        self.assertFalse(eligible_for_next_round([{"roundNo": 1, "verdict": "FAIL"}], 2))
        self.assertFalse(eligible_for_next_round([{"roundNo": 1, "verdict": "PASS"}], 3))
        self.assertFalse(eligible_for_next_round([{"roundNo": 1, "verdict": "PASS"}], 1))

    def test_next_round_routing(self):
        results = [{"studentId": 3, "roundNo": 1, "verdict": "PASS"},
                   {"studentId": 1, "roundNo": 1, "verdict": "FAIL"},
                   {"studentId": 2, "roundNo": 1, "verdict": "PASS"},
                   {"studentId": 2, "roundNo": 2, "verdict": "PASS"},
                   {"studentId": 4, "roundNo": 1, "verdict": "PASS"},
                   {"studentId": 4, "roundNo": 2, "verdict": "PASS"},
                   {"studentId": 4, "roundNo": 3, "verdict": "PASS"}]
        out = next_round(results, {"rounds": ["Coding", "Tech", "HR"]})
        self.assertEqual(out["promoted"], [{"studentId": 2, "roundNo": 3}, {"studentId": 3, "roundNo": 2}])
        self.assertEqual(out["eliminated"], [1])
        self.assertEqual(out["completed"], [4])

    def test_release_time(self):
        self.assertEqual(release_time("2026-11-03T10:00:00Z", 90), "2026-11-03T11:30:00Z")


class RankingTests(unittest.TestCase):
    def test_normalises_harsh_and_lenient_graders(self):
        ev = [  # harsh grader (1) scores A 5 / B 3; lenient grader (2) scores C 9 / D 7
            {"studentId": "A", "interviewerId": 1, "criteria": {"tech": 5}},
            {"studentId": "B", "interviewerId": 1, "criteria": {"tech": 3}},
            {"studentId": "C", "interviewerId": 2, "criteria": {"tech": 9}},
            {"studentId": "D", "interviewerId": 2, "criteria": {"tech": 7}}]
        rows = aggregate_ranking(ev)
        self.assertEqual([r["studentId"] for r in rows], ["A", "C", "B", "D"])  # A/C tie -> id; B/D tie -> id
        self.assertEqual([r["rank"] for r in rows], [1, 2, 3, 4])
        self.assertEqual(set(rows[0]), {"studentId", "perCriterion", "total", "rank"})

    def test_deterministic_and_weights(self):
        ev = [{"studentId": 1, "interviewerId": 1, "criteria": {"a": 1, "b": 9}},
              {"studentId": 2, "interviewerId": 1, "criteria": {"a": 9, "b": 1}}]
        self.assertEqual(aggregate_ranking(ev, {"a": 3, "b": 1})[0]["studentId"], 2)
        self.assertEqual(aggregate_ranking(ev), aggregate_ranking(list(reversed(ev))))
        self.assertEqual(aggregate_ranking([]), [])


if __name__ == "__main__":
    unittest.main()
