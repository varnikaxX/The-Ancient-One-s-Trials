"""Pure-logic tests: no database needed."""
import os
import unittest
from datetime import datetime, timezone

from tests import base  # noqa: F401  (sets env + sys.path)
from app.errors import ApiError
from app.schemas import Choice
from app.services import ics_service, preference_service, solver_stub
from app.security import create_token, decode_token, hash_password, verify_password


def choices(*pairs):
    return [Choice(slot_id=s, rank=r) for s, r in pairs]


class PreferenceValidation(unittest.TestCase):
    def test_accepts_one_to_three(self):
        self.assertEqual(len(preference_service.validate_choices(choices((1, 1)))), 1)
        self.assertEqual([c.rank for c in preference_service.validate_choices(choices((3, 3), (1, 1), (2, 2)))], [1, 2, 3])

    def test_rejects_more_than_three(self):
        with self.assertRaises(ApiError) as cm:
            preference_service.validate_choices(choices((1, 1), (2, 2), (3, 3), (4, 3)))
        self.assertEqual(cm.exception.code, "VALIDATION")

    def test_rejects_empty(self):
        with self.assertRaises(ApiError):
            preference_service.validate_choices([])

    def test_rejects_duplicate_rank(self):
        with self.assertRaises(ApiError):
            preference_service.validate_choices(choices((1, 1), (2, 1)))

    def test_rejects_rank_out_of_range(self):
        with self.assertRaises(ApiError):
            preference_service.validate_choices(choices((1, 4)))

    def test_rejects_same_slot_twice(self):
        with self.assertRaises(ApiError):
            preference_service.validate_choices(choices((1, 1), (1, 2)))

    def test_round_eligibility(self):
        self.assertTrue(preference_service.eligible_for_round([], 1))
        self.assertFalse(preference_service.eligible_for_round([], 2))
        self.assertTrue(preference_service.eligible_for_round([1], 2))
        self.assertFalse(preference_service.eligible_for_round([1], 3))


class Security(unittest.TestCase):
    def test_password_roundtrip(self):
        h = hash_password("secret-123")
        self.assertTrue(h.startswith("$argon2"))
        self.assertTrue(verify_password("secret-123", h))
        self.assertFalse(verify_password("nope", h))

    def test_token_roundtrip_and_expiry(self):
        claims = decode_token(create_token(5, "STUDENT"))
        self.assertEqual((claims["sub"], claims["role"]), ("5", "STUDENT"))
        with self.assertRaises(ApiError) as cm:
            decode_token(create_token(5, "STUDENT", minutes=-1))
        self.assertEqual(cm.exception.code, "UNAUTHORIZED")
        with self.assertRaises(ApiError):
            decode_token("garbage")


class IcsContent(unittest.TestCase):
    INTERVIEW = {"id": 42, "studentId": 11, "studentName": "Stephen Strange", "companyId": 1, "companyName": "Kamar-Taj Labs",
                 "roundNo": 2, "type": "PANEL", "start": "2026-11-03T09:00:00Z", "end": "2026-11-03T09:30:00Z",
                 "room": "Sanctum Hall", "status": "CONFIRMED", "version": 3,
                 "panel": [{"interviewerId": 2, "name": "Arjun Mehta", "skill": "Tech"},
                           {"interviewerId": 3, "name": "Meera Kapoor", "skill": "HR"}]}

    def test_event_fields(self):
        text = ics_service.build_ics_for(self.INTERVIEW).decode().replace("\r\n ", "")   # RFC 5545 line unfolding
        self.assertIn("BEGIN:VCALENDAR", text)
        self.assertIn("UID:interview-42@ancient-ones-trials", text)
        self.assertIn("DTSTART:20261103T090000Z", text)
        self.assertIn("DTEND:20261103T093000Z", text)
        self.assertIn("LOCATION:Sanctum Hall", text)
        self.assertIn("Arjun Mehta", text)
        self.assertIn("Meera Kapoor", text)
        self.assertIn("SEQUENCE:3", text)
        self.assertIn("BEGIN:VALARM", text)
        self.assertIn("TRIGGER:-PT1H", text)
        self.assertIn("STATUS:CONFIRMED", text)

    def test_parses_with_icalendar(self):
        from icalendar import Calendar
        cal = Calendar.from_ical(ics_service.build_ics_for(self.INTERVIEW))
        ev = [c for c in cal.walk() if c.name == "VEVENT"][0]
        self.assertEqual(str(ev["uid"]), "interview-42@ancient-ones-trials")


class StubSolverShape(unittest.TestCase):
    def data(self):
        slot = lambda i, iv, t, room: {"slotId": i, "interviewerId": iv, "start": f"2026-11-03T{t}:00Z",
                                       "end": f"2026-11-03T{t[:2]}:30:00Z", "roomId": room, "skillTags": ["Coding"]}
        return {"roundNo": 1, "slots": [slot(1, 7, "09", 1), slot(2, 7, "10", 1)], "rooms": [{"roomId": 1}],
                "students": [{"studentId": 11, "prefs": [{"slotId": 1, "rank": 1}]},
                             {"studentId": 12, "prefs": [{"slotId": 1, "rank": 1}, {"slotId": 2, "rank": 2}]},
                             {"studentId": 13, "prefs": [{"slotId": 1, "rank": 1}]}],
                "panelRequirements": {"companyId": 3, "requiredSkills": []}, "weights": {}}

    def test_never_double_books_and_reports_unmatched(self):
        out = solver_stub.solve_batch(self.data())
        got = {a["studentId"]: a["slotId"] for a in out["assignments"]}
        self.assertEqual(got, {11: 1, 12: 2})
        self.assertEqual(out["unmatched"], [{"studentId": 13, "reason": "ALL_PREFERRED_SLOTS_TAKEN"}])
        self.assertEqual(out["stats"]["matched"], 2)
        self.assertEqual(set(out), {"status", "objectiveValue", "assignments", "unmatched", "stats"})


if __name__ == "__main__":
    unittest.main()
