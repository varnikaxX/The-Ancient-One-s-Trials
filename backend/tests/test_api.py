"""API tests against a real PostgreSQL (and eager Celery)."""
import threading
import unittest
from datetime import timedelta
from unittest import mock

import psycopg

from tests.base import ApiTestCase, day, ts, PASSWORD
from tests import base

COORD = "coordinator@trials.edu"
ARJUN = "arjun@kamartaj.com"      # company 1, Coding+Tech
MEERA = "meera@kamartaj.com"      # company 1, Coding+HR


class AuthAndGuards(ApiTestCase):
    def test_register_login_me(self):
        token, uid = self.register(1)
        me = self.client.get("/api/me", headers=self.h(token, False))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["role"], "STUDENT")
        self.assertIn("regNo", me.json()["profile"])

    def test_error_shape_and_codes(self):
        r = self.client.get("/api/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": {"code": "UNAUTHORIZED", "message": "Missing bearer token"}})
        r = self.client.post("/api/auth/login", json={"email": COORD, "password": "wrong"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "UNAUTHORIZED"))
        r = self.client.post("/api/auth/register", json={"name": "x"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION"))

    def test_duplicate_registration(self):
        body = {"name": "D", "email": "dup@t.test", "password": PASSWORD, "regNo": "DUP1", "branch": "CSE", "skills": []}
        self.assertEqual(self.client.post("/api/auth/register", json=body).status_code, 200)
        r = self.client.post("/api/auth/register", json=dict(body, regNo="DUP2"))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "DUPLICATE"))

    def test_role_guards(self):
        student, _ = self.register(2)
        coord = self.login(COORD)
        iv = self.login(ARJUN)
        checks = [
            ("post", "/api/coordinator/matching/run", student, {"roundNo": 1}),
            ("get", "/api/coordinator/drafts?roundNo=1", iv, None),
            ("put", "/api/interviewer/availability", student, {"slots": []}),
            ("get", "/api/interviewer/proposals", coord, None),
            ("post", "/api/student/preferences", iv, {"companyId": 1, "roundNo": 1, "choices": []}),
            ("get", "/api/student/status", coord, None),
        ]
        for method, path, token, body in checks:
            r = getattr(self.client, method)(path, headers=self.h(token), **({"json": body} if body is not None else {}))
            self.assertEqual((path, r.status_code, r.json()["error"]["code"]), (path, 403, "FORBIDDEN"))

    def test_write_requires_idempotency_key(self):
        student, _ = self.register(3)
        r = self.client.post("/api/student/preferences", headers={"Authorization": f"Bearer {student}"},
                             json={"companyId": 1, "roundNo": 1, "choices": []})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION"))


class Preferences(ApiTestCase):
    def test_max_three_and_unique_ranks_over_http(self):
        student, _ = self.register(4)
        arjun = self.login(ARJUN)
        slots = self.set_availability(arjun, day(5, 9), 3)
        ids = [s["slotId"] for s in slots][:4]
        r = self.client.post("/api/student/preferences", headers=self.h(student), json={
            "companyId": 1, "roundNo": 1, "choices": [{"slotId": i, "rank": n + 1} for n, i in enumerate(ids)]})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION"))
        r = self.client.post("/api/student/preferences", headers=self.h(student), json={
            "companyId": 1, "roundNo": 1, "choices": [{"slotId": ids[0], "rank": 1}, {"slotId": ids[1], "rank": 1}]})
        self.assertEqual(r.status_code, 400)

    def test_locked_round_rejected(self):
        student, _ = self.register(5)
        slots = self.set_availability(self.login(ARJUN), day(5, 9), 1)
        r = self.client.post("/api/student/preferences", headers=self.h(student), json={
            "companyId": 1, "roundNo": 2, "choices": [{"slotId": slots[0]["slotId"], "rank": 1}]})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION"))

    def test_submit_does_not_call_solver(self):
        student, _ = self.register(6)
        slots = self.set_availability(self.login(ARJUN), day(5, 9), 1)
        with mock.patch("app.services.matching_service.get_solver", side_effect=AssertionError("solver must not run")):
            r = self.client.post("/api/student/preferences", headers=self.h(student), json={
                "companyId": 1, "roundNo": 1, "choices": [{"slotId": slots[0]["slotId"], "rank": 1}]})
        self.assertEqual((r.status_code, r.json()), (200, {"status": "PENDING"}))

    def test_idempotent_replay_one_side_effect(self):
        student, uid = self.register(7)
        slots = self.set_availability(self.login(ARJUN), day(5, 9), 2)
        key = self.key()
        body = {"companyId": 1, "roundNo": 1, "choices": [{"slotId": slots[0]["slotId"], "rank": 1}]}
        a = self.client.post("/api/student/preferences", headers=self.h(student, key), json=body)
        # a retry with the same key but a DIFFERENT body must still replay the first response, not re-run
        b = self.client.post("/api/student/preferences", headers=self.h(student, key),
                             json=dict(body, choices=[{"slotId": slots[1]["slotId"], "rank": 1}]))
        self.assertEqual((a.status_code, a.json()), (b.status_code, b.json()))
        rows = self.sql("SELECT slot_id FROM slot_preferences WHERE student_id = %s", (uid,))
        self.assertEqual(rows, [(slots[0]["slotId"],)])
        keys = self.sql("SELECT count(*) FROM idempotency_keys WHERE key LIKE %s", (f"{uid}:%:{key}",))
        self.assertEqual(keys[0][0], 1)

    def test_idempotent_concurrent_retries(self):
        student, uid = self.register(8)
        slots = self.set_availability(self.login(ARJUN), day(5, 9), 1)
        key = self.key()
        body = {"companyId": 1, "roundNo": 1, "choices": [{"slotId": slots[0]["slotId"], "rank": 1}]}
        out = []
        threads = [threading.Thread(target=lambda: out.append(
            self.client.post("/api/student/preferences", headers=self.h(student, key), json=body).json())) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(out, [{"status": "PENDING"}] * 6)
        self.assertEqual(self.sql("SELECT count(*) FROM slot_preferences WHERE student_id = %s", (uid,))[0][0], 1)


class DatabaseIsTheFinalGuard(ApiTestCase):
    """Acceptance: the DB rejects double booking even if application checks are bypassed."""

    def _fixture(self):
        n = self.sql("SELECT count(*) FROM students")[0][0]
        arjun = self.login(ARJUN)
        slots = self.set_availability(arjun, day(7, 9), 1)
        return slots

    def test_sql_rejects_overlapping_interviewer_booking(self):
        slots = self._fixture()
        (sid, start, end), = self.sql("SELECT id, start_ts, end_ts FROM availability_slots WHERE id = %s", (slots[0]["slotId"],))
        _, s1 = self.register(20)
        _, s2 = self.register(21)
        with psycopg.connect(base.os.environ["DATABASE_URL"]) as c:
            ids = []
            for stu in (s1, s2):
                ids.append(c.execute(
                    "INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status) "
                    "VALUES (%s, 1, 1, %s, %s, NULL, 'CONFIRMED') RETURNING id", (stu, start, end)).fetchone()[0])
            c.execute("INSERT INTO interview_panel (interview_id, interviewer_id, slot_id, start_ts, end_ts, booked) "
                      "VALUES (%s, 2, %s, %s, %s, true)", (ids[0], sid, start, end))
            # same slot twice -> UNIQUE(slot_id)
            with self.assertRaises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO interview_panel (interview_id, interviewer_id, slot_id, start_ts, end_ts, booked) "
                          "VALUES (%s, 2, %s, %s, %s, true)", (ids[1], sid, start, end))
            c.rollback()

    def test_sql_rejects_room_and_student_overlap(self):
        _, s1 = self.register(22)
        start, end = day(8, 9), day(8, 9) + timedelta(minutes=30)
        with psycopg.connect(base.os.environ["DATABASE_URL"]) as c:
            c.execute("INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status) "
                      "VALUES (%s, 1, 1, %s, %s, 1, 'CONFIRMED')", (s1, start, end))
            _, s2 = self.register(23)
            with self.assertRaises(psycopg.errors.ExclusionViolation):          # same room, overlapping time
                c.execute("INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status) "
                          "VALUES (%s, 2, 1, %s, %s, 1, 'CONFIRMED')", (s2, start + timedelta(minutes=10), end + timedelta(minutes=10)))
            c.rollback()
        with psycopg.connect(base.os.environ["DATABASE_URL"]) as c:
            c.execute("INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status) "
                      "VALUES (%s, 1, 1, %s, %s, 2, 'CONFIRMED')", (s1, start, end))
            with self.assertRaises(psycopg.errors.ExclusionViolation):          # same student, overlapping time
                c.execute("INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status) "
                          "VALUES (%s, 2, 2, %s, %s, 3, 'CONFIRMED')", (s1, start, end))
            c.rollback()

    def test_concurrent_commit_exactly_one_wins(self):
        """Two coordinators approve two different drafts that (through a bug) both claim room 3 at the
        same time. Application checks are not what saves us — the exclusion constraint is. Exactly one
        approval commits; the other gets SLOT_TAKEN."""
        coord = self.login(COORD)
        start = day(9, 9)
        end = start + timedelta(minutes=30)
        _, s1 = self.register(30)
        _, s2 = self.register(31)
        with psycopg.connect(base.os.environ["DATABASE_URL"], autocommit=True) as c:
            drafts = []
            for rn in (1, 2):
                v = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM schedule_drafts WHERE round_no = %s", (rn,)).fetchone()[0]
                drafts.append(c.execute("INSERT INTO schedule_drafts (round_no, version) VALUES (%s, %s) RETURNING id, version", (rn, v)).fetchone())
            for (did, _), stu, rn, iv in zip(drafts, (s1, s2), (1, 2), (2, 3)):
                iid = c.execute("INSERT INTO interviews (student_id, company_id, round_no, start_ts, end_ts, room_id, status, draft_id) "
                                "VALUES (%s, 1, %s, %s, %s, 3, 'INTERVIEWER_CONFIRMED', %s) RETURNING id", (stu, rn, start, end, did)).fetchone()[0]
                slot = c.execute("INSERT INTO availability_slots (interviewer_id, start_ts, end_ts, status, room_id) "
                                 "VALUES (%s, %s, %s, 'HELD', 3) RETURNING id", (iv, start, end)).fetchone()[0]
                c.execute("INSERT INTO interview_panel (interview_id, interviewer_id, slot_id, start_ts, end_ts) VALUES (%s, %s, %s, %s, %s)",
                          (iid, iv, slot, start, end))
        gate, results = threading.Barrier(2), []

        def approve(did, version):
            gate.wait()
            r = self.client.post(f"/api/coordinator/drafts/{did}/approve", headers=self.h(coord), json={"version": version})
            results.append((r.status_code, r.json()))

        ts_ = [threading.Thread(target=approve, args=(d, v)) for d, v in drafts]
        [t.start() for t in ts_]
        [t.join() for t in ts_]
        codes = sorted(code for code, _ in results)
        self.assertEqual(codes, [200, 409], results)
        loser = [b for code, b in results if code == 409][0]
        self.assertEqual(loser["error"]["code"], "SLOT_TAKEN")
        confirmed = self.sql("SELECT count(*) FROM interviews WHERE room_id = 3 AND start_ts = %s AND status = 'CONFIRMED'", (start,))[0][0]
        self.assertEqual(confirmed, 1)


class StaleDraft(ApiTestCase):
    def test_old_version_rejected(self):
        coord = self.login(COORD)
        with psycopg.connect(base.os.environ["DATABASE_URL"], autocommit=True) as c:
            old = c.execute("INSERT INTO schedule_drafts (round_no, version, status) VALUES (3, 1, 'DRAFT') RETURNING id").fetchone()[0]
            new = c.execute("INSERT INTO schedule_drafts (round_no, version, status) VALUES (3, 2, 'DRAFT') RETURNING id").fetchone()[0]
        r = self.client.post(f"/api/coordinator/drafts/{old}/approve", headers=self.h(coord), json={"version": 1})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "STALE_DRAFT"))
        r = self.client.post(f"/api/coordinator/drafts/{new}/approve", headers=self.h(coord), json={"version": 1})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "STALE_DRAFT"))     # wrong version number
        r = self.client.post(f"/api/coordinator/drafts/{new}/approve", headers=self.h(coord), json={"version": 2})
        self.assertEqual((r.status_code, r.json()), (200, {"committed": 0}))
        r = self.client.post(f"/api/coordinator/drafts/{new}/approve", headers=self.h(coord), json={"version": 2})
        self.assertEqual(r.json()["error"]["code"], "STALE_DRAFT")                              # already approved


class OutboxRetry(ApiTestCase):
    def test_mail_outage_keeps_rows_pending_then_recovers(self):
        from app.services import email_service
        from workers import tasks
        self.sql("DELETE FROM outbox")
        self.sql("INSERT INTO outbox (kind, payload) VALUES ('EMAIL', %s::jsonb)",
                 ('{"to":"a@b.test","subject":"s","text":"t","interviewId":null}',))
        with mock.patch.object(email_service, "send_email", side_effect=email_service.EmailError("provider down")):
            stats = tasks.process_outbox()
        self.assertEqual(stats["retry"], 1)
        row = self.sql("SELECT status, attempts, last_error FROM outbox")[0]
        self.assertEqual((row[0], row[1]), ("PENDING", 1))
        self.assertIn("provider down", row[2])
        stats = tasks.process_outbox()                          # provider is back (dry-run)
        self.assertEqual(stats["sent"], 1)
        self.assertEqual(self.sql("SELECT status FROM outbox")[0][0], "SENT")

    def test_fails_permanently_after_max_attempts(self):
        from app.config import settings
        from app.services import email_service
        from workers import tasks
        self.sql("DELETE FROM outbox")
        self.sql("INSERT INTO outbox (kind, payload) VALUES ('EMAIL', %s::jsonb)", ('{"to":"a@b.test","subject":"s","text":"t"}',))
        with mock.patch.object(email_service, "send_email", side_effect=email_service.EmailError("down")):
            for _ in range(settings.outbox_max_attempts):
                tasks.process_outbox()
        row = self.sql("SELECT status, attempts FROM outbox")[0]
        self.assertEqual(row, ("FAILED", settings.outbox_max_attempts))

    def test_confirmation_survives_mail_outage(self):
        """Full approve while the mail provider is down: committed, outbox PENDING, nothing lost."""
        from app.services import email_service
        full = FullFlow
        with mock.patch.object(email_service, "send_email", side_effect=email_service.EmailError("outage")):
            ctx = full.run_until_approved(self)
        self.assertEqual(ctx["approve"]["committed"], 1)
        self.assertEqual(self.sql("SELECT status FROM interviews WHERE id = %s", (ctx["interview_id"],))[0][0], "CONFIRMED")
        self.assertGreater(self.sql("SELECT count(*) FROM outbox WHERE kind = 'EMAIL' AND status = 'PENDING'")[0][0], 0)


class FullFlow(ApiTestCase):
    """The README demo script, end to end through the real HTTP layer, Postgres and (eager) Celery."""

    @staticmethod
    def run_until_approved(t, offset=10, hours=2):
        arjun, coord = t.login(ARJUN), t.login(COORD)
        slots = t.set_availability(arjun, day(offset, 9), hours)
        t.assertEqual(len(slots), int(hours * 2))          # 30-minute slots
        student, sid = t.register(40 + offset)
        picks = [s["slotId"] for s in t.client.get("/api/companies/1/slots?roundNo=1", headers=t.h(student, False)).json()
                 if s["interviewerNames"] == ["Arjun Mehta"]][:3]
        t.assertEqual(
            t.client.post("/api/student/preferences", headers=t.h(student), json={
                "companyId": 1, "roundNo": 1, "choices": [{"slotId": p, "rank": i + 1} for i, p in enumerate(picks)]}).json(),
            {"status": "PENDING"})
        job = t.client.post("/api/coordinator/matching/run", headers=t.h(coord), json={"roundNo": 1})
        t.assertEqual(job.status_code, 200, job.text)
        t.assertIn("jobId", job.json())
        drafts = t.client.get("/api/coordinator/drafts?roundNo=1", headers=t.h(coord, False)).json()
        draft = drafts[0]
        t.assertEqual((draft["status"], draft["matched"], draft["unmatched"]), ("DRAFT", 1, 0))
        detail = t.client.get(f"/api/coordinator/drafts/{draft['draftId']}", headers=t.h(coord, False)).json()
        interview = detail["interviews"][0]
        t.assertEqual(interview["status"], "PROPOSED")
        t.assertEqual(interview["panel"][0]["name"], "Arjun Mehta")
        t.assertEqual(interview["start"], ts(day(offset, 9)))      # rank-1 got honoured
        props = t.client.get("/api/interviewer/proposals", headers=t.h(arjun, False)).json()
        t.assertEqual([p["id"] for p in props], [interview["id"]])
        conf = t.client.post(f"/api/interviewer/interviews/{interview['id']}/confirm", headers=t.h(arjun))
        t.assertEqual(conf.json()["status"], "INTERVIEWER_CONFIRMED")
        appr = t.client.post(f"/api/coordinator/drafts/{draft['draftId']}/approve", headers=t.h(coord),
                             json={"version": draft["version"]})
        t.assertEqual(appr.status_code, 200, appr.text)
        return {"arjun": arjun, "coord": coord, "student": student, "student_id": sid, "interview_id": interview["id"],
                "approve": appr.json(), "draft": draft, "picks": picks}

    def test_demo_script(self):
        ctx = self.run_until_approved(self, 12)
        iid, student, arjun, coord = ctx["interview_id"], ctx["student"], ctx["arjun"], ctx["coord"]
        self.assertEqual(ctx["approve"], {"committed": 1})
        # slot is BOOKED; companies list no longer offers it
        self.assertEqual(self.sql("SELECT status FROM availability_slots WHERE id = %s", (ctx["picks"][0],))[0][0], "BOOKED")
        offered = [s["slotId"] for s in self.client.get("/api/companies/1/slots?roundNo=1", headers=self.h(student, False)).json()]
        self.assertNotIn(ctx["picks"][0], offered)
        # student view + notification + email rows
        st = self.client.get("/api/student/status", headers=self.h(student, False)).json()
        self.assertEqual(st["interviews"][0]["status"], "CONFIRMED")
        self.assertIn("confirmed", st["statusText"].lower())
        notes = self.client.get("/api/notifications", headers=self.h(student, False)).json()
        self.assertIn("INTERVIEW_CONFIRMED", [n["type"] for n in notes])
        self.assertGreater(self.sql("SELECT count(*) FROM outbox WHERE kind='EMAIL' AND status='SENT'")[0][0], 0)
        r = self.client.post(f"/api/notifications/{notes[0]['id']}/read", headers=self.h(student))
        self.assertEqual(r.json()["read"], True)
        # ICS for the student and the panelist, not for a stranger
        r = self.client.get(f"/api/student/interviews/{iid}/ics", headers=self.h(student, False))
        self.assertEqual((r.status_code, r.headers["content-type"].split(";")[0]), (200, "text/calendar"))
        self.assertIn("Arjun Mehta", r.text.replace("\r\n ", ""))
        self.assertEqual(self.client.get(f"/api/student/interviews/{iid}/ics", headers=self.h(arjun, False)).status_code, 200)
        other, _ = self.register(99)
        self.assertEqual(self.client.get(f"/api/student/interviews/{iid}/ics", headers=self.h(other, False)).status_code, 403)
        # calendar feed
        cal = self.client.get("/api/calendar", headers=self.h(student, False)).json()
        self.assertEqual([e["id"] for e in cal], [iid])
        self.assertEqual(set(cal[0]), {"id", "title", "start", "end", "room", "interviewerNames", "status"})
        # result -> released (delay 0 for the test) -> round 2 unlocked
        self.sql("UPDATE config SET value = '0' WHERE key = 'result_delay_minutes'")
        res = self.client.post(f"/api/interviewer/interviews/{iid}/result", headers=self.h(arjun), json={"verdict": "PASS", "score": 88})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["verdict"], "PASS")
        st = self.client.get("/api/student/status", headers=self.h(student, False)).json()
        self.assertEqual(st["passedRounds"], [1])
        self.assertEqual(st["results"][0]["verdict"], "PASS")
        slots2 = self.client.get("/api/companies/1/slots?roundNo=2", headers=self.h(student, False)).json()
        self.assertTrue(slots2, "Arjun has Tech tag and free slots left")
        r = self.client.post("/api/student/preferences", headers=self.h(student), json={
            "companyId": 1, "roundNo": 2, "choices": [{"slotId": slots2[0]["slotId"], "rank": 1}]})
        self.assertEqual(r.json(), {"status": "PENDING"})
        self.sql("UPDATE config SET value = '30' WHERE key = 'result_delay_minutes'")

    def test_result_is_hidden_until_release(self):
        ctx = self.run_until_approved(self, 13)
        self.sql("UPDATE config SET value = '30' WHERE key = 'result_delay_minutes'")
        self.client.post(f"/api/interviewer/interviews/{ctx['interview_id']}/result", headers=self.h(ctx["arjun"]),
                         json={"verdict": "FAIL", "score": 40})
        st = self.client.get("/api/student/status", headers=self.h(ctx["student"], False)).json()
        self.assertEqual((st["results"], st["passedRounds"]), ([], []))
        self.sql("UPDATE results SET release_at = now() - interval '1 minute'")
        from workers.tasks import release_results_task
        self.assertEqual(release_results_task()["released"], 1)
        st = self.client.get("/api/student/status", headers=self.h(ctx["student"], False)).json()
        self.assertEqual(st["results"][0]["verdict"], "FAIL")
        self.assertEqual(st["passedRounds"], [])

    def test_interviewer_cancel_triggers_repair(self):
        ctx = self.run_until_approved(self, 14)
        iid, arjun = ctx["interview_id"], ctx["arjun"]
        meera = self.login(MEERA)
        self.set_availability(meera, day(14, 9), 2)           # Meera offers the same times -> SWAP_INTERVIEWER
        r = self.client.post(f"/api/interviewer/interviews/{iid}/cancel", headers=self.h(arjun), json={"reason": "sick"})
        self.assertEqual((r.status_code, r.json()), (200, {"flaggedInterviews": [iid]}))
        row = self.sql("SELECT status, version FROM interviews WHERE id = %s", (iid,))[0]
        self.assertEqual(row[0], "CONFIRMED", "repair ran inline (eager) and re-confirmed")
        self.assertEqual(row[1], 2, "interview version bumped")
        view = self.client.get("/api/calendar", headers=self.h(ctx["student"], False)).json()[0]
        self.assertEqual(view["interviewerNames"], ["Meera Kapoor"])
        types = [n["type"] for n in self.client.get("/api/notifications", headers=self.h(ctx["student"], False)).json()]
        self.assertIn("INTERVIEW_CHANGED", types)
        # still no double booking anywhere
        self.assertEqual(self.sql("SELECT count(*) FROM interview_panel WHERE booked")[0][0],
                         self.sql("SELECT count(DISTINCT slot_id) FROM interview_panel WHERE booked")[0][0])

    def test_repair_moves_to_nearest_free_slot(self):
        ctx = self.run_until_approved(self, 15)             # Arjun has 3 other free slots
        self.client.post(f"/api/interviewer/interviews/{ctx['interview_id']}/cancel", headers=self.h(ctx["arjun"]), json={"reason": "x"})
        row = self.sql("SELECT status, version, start_ts FROM interviews WHERE id = %s", (ctx["interview_id"],))[0]
        self.assertEqual((row[0], row[1]), ("CONFIRMED", 2))
        self.assertNotEqual(row[2], day(15, 9))

    def test_unresolved_repair_notifies_student(self):
        self.sql("DELETE FROM availability_slots WHERE interviewer_id <> 2")     # drop other seeded slots
        ctx = self.run_until_approved(self, 16, hours=0.5)  # a single slot -> nowhere to go
        r = self.client.post(f"/api/interviewer/interviews/{ctx['interview_id']}/cancel", headers=self.h(ctx["arjun"]), json={"reason": "x"})
        self.assertEqual(r.json(), {"flaggedInterviews": [ctx["interview_id"]]})
        self.assertEqual(self.sql("SELECT status FROM interviews WHERE id = %s", (ctx["interview_id"],))[0][0], "CANCELLED")
        types = [n["type"] for n in self.client.get("/api/notifications", headers=self.h(ctx["student"], False)).json()]
        self.assertIn("INTERVIEW_CANCELLED", types)
        self.assertEqual(self.sql("SELECT count(*) FROM interview_panel WHERE interview_id = %s", (ctx["interview_id"],))[0][0], 0)

    def test_matching_unmatched_gets_match_failed(self):
        arjun, coord = self.login(ARJUN), self.login(COORD)
        slots = self.set_availability(arjun, day(20, 9), 1)
        s_a, _ = self.register(60)
        s_b, id_b = self.register(61)
        want = slots[0]["slotId"]
        for tok in (s_a, s_b):
            self.client.post("/api/student/preferences", headers=self.h(tok), json={
                "companyId": 1, "roundNo": 1, "choices": [{"slotId": want, "rank": 1}]})
        self.client.post("/api/coordinator/matching/run", headers=self.h(coord), json={"roundNo": 1})
        d = self.client.get("/api/coordinator/drafts?roundNo=1", headers=self.h(coord, False)).json()[0]
        self.assertEqual((d["matched"], d["unmatched"]), (1, 1))
        loser = s_b if self.sql("SELECT count(*) FROM interviews WHERE student_id = %s AND status <> 'CANCELLED'", (id_b,))[0][0] == 0 else s_a
        types = [n["type"] for n in self.client.get("/api/notifications", headers=self.h(loser, False)).json()]
        self.assertIn("MATCH_FAILED", types)
        detail = self.client.get(f"/api/coordinator/drafts/{d['draftId']}", headers=self.h(coord, False)).json()
        self.assertEqual(len(detail["unmatchedStudents"]), 1)

    def test_rematch_supersedes_old_draft(self):
        arjun, coord = self.login(ARJUN), self.login(COORD)
        slots = self.set_availability(arjun, day(25, 9), 1)
        tok, _ = self.register(70)
        self.client.post("/api/student/preferences", headers=self.h(tok), json={
            "companyId": 1, "roundNo": 1, "choices": [{"slotId": slots[0]["slotId"], "rank": 1}]})
        self.client.post("/api/coordinator/matching/run", headers=self.h(coord), json={"roundNo": 1})
        self.client.post("/api/coordinator/matching/run", headers=self.h(coord), json={"roundNo": 1})
        drafts = self.client.get("/api/coordinator/drafts?roundNo=1", headers=self.h(coord, False)).json()
        self.assertEqual(drafts[0]["status"], "DRAFT")
        self.assertEqual(drafts[1]["status"], "SUPERSEDED")
        self.assertGreater(drafts[0]["version"], drafts[1]["version"])


class StretchEvaluations(ApiTestCase):
    def test_blinded_evaluation_and_ranking(self):
        ctx = FullFlow.run_until_approved(self, 30)
        iid = ctx["interview_id"]
        r = self.client.post(f"/api/interviewer/interviews/{iid}/evaluation", headers=self.h(ctx["arjun"]),
                             json={"criteria": {"problemSolving": 8, "communication": 6}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["total"], 7.0)
        # no endpoint exposes evaluations to interviewers or students
        self.assertEqual(self.client.get("/api/coordinator/ranking?companyId=1", headers=self.h(ctx["arjun"], False)).status_code, 403)
        rank = self.client.get("/api/coordinator/ranking?companyId=1", headers=self.h(ctx["coord"], False))
        self.assertEqual(rank.status_code, 200)
        self.assertEqual(rank.json()[0]["studentId"], ctx["student_id"])


if __name__ == "__main__":
    unittest.main()
