import copy
import unittest

import _util as u
from scheduler import reschedule


def base(free_extra=(), student_prefs=(1, 3), cancel_slots=(1,)):
    """Interviewer 7 cancels slot 1 (student 11). Slot 4 (student 12, interviewer 8) stays frozen."""
    slots = [
        u.slot(1, 7, 0, room_id=1),                       # cancelled
        u.slot(4, 8, 60, room_id=1),                      # frozen interview
    ]
    free = list(free_extra)
    data = u.batch(slots + free, [u.student(11, *student_prefs), u.student(12, 4)], rooms=[1, 2, 3])
    data["currentInterviews"] = [
        {"interviewId": 100, "studentId": 11, "slotId": 1, "interviewerIds": [7], "roomId": 1, "roundNo": 1},
        {"interviewId": 101, "studentId": 12, "slotId": 4, "interviewerIds": [8], "roomId": 1, "roundNo": 1},
    ]
    data["cancelled"] = {"interviewerId": 7, "slotIds": list(cancel_slots)}
    data["freeSlots"] = copy.deepcopy(free)
    data["moveWeights"] = {"movePenalty": 500, "swapInterviewer": 50, "nextRanked": 150, "nearestSlot": 300}
    return data


class RescheduleTests(unittest.TestCase):
    def test_swap_interviewer_preferred_over_next_ranked_and_nearest(self):
        free = [u.slot(2, 9, 0, room_id=2),               # same time, same skill -> SWAP
                u.slot(3, 9, 90, room_id=2),              # student's rank-2 slot -> NEXT_RANKED
                u.slot(5, 9, 30, room_id=2)]              # nearest
        res = reschedule(base(free))
        mv = res["moves"][0]
        self.assertEqual(mv["strategy"], "SWAP_INTERVIEWER")
        self.assertEqual((mv["fromSlotId"], mv["toSlotId"], mv["newInterviewerIds"]), (1, 2, [9]))
        self.assertEqual(res["untouched"], 1)
        self.assertEqual(res["unresolved"], [])

    def test_swap_needs_overlapping_skill(self):
        free = [u.slot(2, 9, 0, room_id=2, tags=("HR",)), u.slot(3, 9, 90, room_id=2)]
        mv = reschedule(base(free))["moves"][0]
        self.assertEqual(mv["strategy"], "NEXT_RANKED")
        self.assertEqual(mv["toSlotId"], 3)

    def test_nearest_free_when_no_swap_or_ranked(self):
        free = [u.slot(5, 9, 120, room_id=2), u.slot(6, 9, 30, room_id=2, tags=("HR",))]
        mv = reschedule(base(free, student_prefs=(1,)))["moves"][0]
        self.assertEqual(mv["strategy"], "NEAREST_FREE")
        self.assertEqual(mv["toSlotId"], 6)  # closest in time (skill not required for nearest)

    def test_unresolved_reported(self):
        res = reschedule(base([], student_prefs=(1,)))
        self.assertEqual(res["moves"][0]["strategy"], "UNRESOLVED")
        self.assertIsNone(res["moves"][0]["toSlotId"])
        self.assertEqual(res["unresolved"], [11])

    def test_untouched_interviews_unchanged_and_not_moved(self):
        free = [u.slot(2, 9, 0, room_id=2)]
        res = reschedule(base(free))
        moved = {m["interviewId"] for m in res["moves"]}
        self.assertEqual(moved, {100})
        self.assertEqual(res["untouched"], 1)

    def test_cannot_move_onto_frozen_interviewer_or_room(self):
        # Free slot 5 uses interviewer 8 (busy in frozen interview at 60) in an overlapping window.
        free = [u.slot(5, 8, 75, room_id=2)]
        res = reschedule(base(free, student_prefs=(1,)))
        self.assertEqual(res["moves"][0]["strategy"], "UNRESOLVED")
        # Same room as frozen interview (room 1 at minute 60) is also blocked.
        free = [u.slot(5, 9, 60, room_id=1)]
        res = reschedule(base(free, student_prefs=(1,)))
        self.assertEqual(res["moves"][0]["strategy"], "UNRESOLVED")

    def test_two_cancelled_share_free_slots_without_collision(self):
        slots = [u.slot(1, 7, 0, room_id=1), u.slot(2, 7, 30, room_id=1)]
        free = [u.slot(3, 9, 0, room_id=2), u.slot(4, 9, 30, room_id=2)]
        data = u.batch(slots + free, [u.student(11, 1, 3), u.student(12, 2, 3)], rooms=[1, 2])
        data["currentInterviews"] = [
            {"interviewId": 1, "studentId": 11, "slotId": 1, "interviewerIds": [7], "roomId": 1, "roundNo": 1},
            {"interviewId": 2, "studentId": 12, "slotId": 2, "interviewerIds": [7], "roomId": 1, "roundNo": 1}]
        data["cancelled"] = {"interviewerId": 7, "slotIds": [1, 2]}
        data["freeSlots"] = free
        res = reschedule(data)
        targets = [m["toSlotId"] for m in res["moves"]]
        self.assertEqual(sorted(targets), [3, 4])
        self.assertEqual(res["unresolved"], [])

    def test_cancel_by_interviewer_only(self):
        free = [u.slot(2, 9, 0, room_id=2)]
        data = base(free)
        data["cancelled"] = {"interviewerId": 7}
        res = reschedule(data)
        self.assertEqual([m["interviewId"] for m in res["moves"]], [100])

    def test_nothing_affected(self):
        data = base([])
        data["cancelled"] = {"interviewerId": 99, "slotIds": [999]}
        res = reschedule(data)
        self.assertEqual(res["moves"], [])
        self.assertEqual(res["untouched"], 2)

    def test_empty_input_safe(self):
        res = reschedule({})
        self.assertEqual(res, {"status": "OPTIMAL", "moves": [], "untouched": 0, "unresolved": []})

    def test_deterministic(self):
        free = [u.slot(2, 9, 0, room_id=2), u.slot(3, 10, 0, room_id=3)]
        a = reschedule(base(free))
        b = reschedule(base(list(reversed(free))))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
