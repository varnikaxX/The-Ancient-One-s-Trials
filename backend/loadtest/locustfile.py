"""Deadline-rush load test.

    locust -f loadtest/locustfile.py --host http://localhost:8000 --users 301 --spawn-rate 50 --headless -t 2m

Prereqs: migrated+seeded DB, API + `celery -A workers.celery_app worker -B` running, and some open slots
(the seed adds 12 on 2026-11-03; ADD_SLOTS below makes more through the interviewer API).
Every simulated student: register -> login -> pick up to 3 slots -> POST /student/preferences with an
Idempotency-Key (and a deliberate RETRY with the SAME key — it must return the identical response).
One coordinator user triggers matching, then approves the newest draft. On test stop the DB is audited:
no interviewer, room or student may hold overlapping CONFIRMED interviews.
"""
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, events, task

COMPANY_ID = int(os.environ.get("LT_COMPANY_ID", "1"))
ROUND_NO = int(os.environ.get("LT_ROUND_NO", "1"))
COORD = (os.environ.get("LT_COORD_EMAIL", "coordinator@trials.edu"), os.environ.get("LT_COORD_PASSWORD", "Passw0rd!"))
INTERVIEWER = (os.environ.get("LT_IV_EMAIL", "arjun@kamartaj.com"), os.environ.get("LT_IV_PASSWORD", "Passw0rd!"))
_seeded = {"done": False}


EXPECTED_409 = ("SLOT_TAKEN", "DUPLICATE", "STALE_DRAFT")      # documented business rejections, not failures


def post_expecting_409(client, url, name, **kw):
    """POST; 200 and the contract 409 codes are successes, anything else (500s, 401s, ...) is a real failure."""
    with client.post(url, name=name, catch_response=True, **kw) as r:
        if r.status_code == 409 and r.json().get("error", {}).get("code") in EXPECTED_409:
            r.success()
        elif r.status_code != 200:
            r.failure(f"{r.status_code} {r.text[:120]}")
        return r


def hdr(token, key=None):
    h = {"Authorization": f"Bearer {token}"}
    if key:
        h["Idempotency-Key"] = key
    return h


@events.test_start.add_listener
def add_slots(environment, **_):
    """Give the interviewer many extra slots so 300 students have something to fight over."""
    import requests
    base = environment.host
    r = requests.post(f"{base}/api/auth/login", json={"email": INTERVIEWER[0], "password": INTERVIEWER[1]})
    if r.status_code != 200:
        return
    token = r.json()["token"]
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=8, minute=0, second=0, microsecond=0)
    ranges = [{"start": (start + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "end": (start + timedelta(days=d, hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")} for d in range(5)]
    requests.put(f"{base}/api/interviewer/availability", json={"slots": ranges}, headers=hdr(token))


class Student(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        n = uuid.uuid4().hex[:10]
        self.email = f"lt_{n}@load.test"
        r = self.client.post("/api/auth/register", name="register", json={
            "name": f"LT {n}", "email": self.email, "password": "Passw0rd!", "regNo": f"LT{n}", "branch": "CSE", "skills": ["Coding"]})
        if r.status_code != 200:
            self.token = None
            return
        r = self.client.post("/api/auth/login", name="login", json={"email": self.email, "password": "Passw0rd!"})
        self.token = r.json()["token"] if r.status_code == 200 else None

    @task
    def rank_and_submit(self):
        if not self.token:
            return
        with self.client.get(f"/api/companies/{COMPANY_ID}/slots?roundNo={ROUND_NO}", name="slots", headers=hdr(self.token), catch_response=True) as r:
            slots = r.json() if r.status_code == 200 else []
        if len(slots) < 3:
            return
        picks = random.sample(slots, 3)
        body = {"companyId": COMPANY_ID, "roundNo": ROUND_NO,
                "choices": [{"slotId": s["slotId"], "rank": i + 1} for i, s in enumerate(picks)]}
        key = str(uuid.uuid4())
        first = post_expecting_409(self.client, "/api/student/preferences", "preferences", json=body, headers=hdr(self.token, key))
        retry = post_expecting_409(self.client, "/api/student/preferences", "preferences (retry same key)", json=body, headers=hdr(self.token, key))
        if first.status_code != retry.status_code or first.json() != retry.json():      # replay must be identical, 409s included
            events.request.fire(request_type="ASSERT", name="idempotent replay", response_time=0, response_length=0,
                                exception=AssertionError("retry with same key returned a different response"))
        self.client.get("/api/student/status", name="status", headers=hdr(self.token))


class Coordinator(HttpUser):
    wait_time = between(15, 30)
    fixed_count = 1                             # exactly one coordinator; the rest of --users are students

    def on_start(self):
        r = self.client.post("/api/auth/login", name="login", json={"email": COORD[0], "password": COORD[1]})
        self.token = r.json()["token"] if r.status_code == 200 else None

    @task
    def run_then_approve(self):
        if not self.token:
            return
        self.client.post("/api/coordinator/matching/run", name="matching/run", json={"roundNo": ROUND_NO},
                         headers=hdr(self.token, str(uuid.uuid4())))
        drafts = self.client.get(f"/api/coordinator/drafts?roundNo={ROUND_NO}", name="drafts", headers=hdr(self.token))
        if drafts.status_code == 200 and drafts.json():
            d = drafts.json()[0]
            if d["status"] == "DRAFT":
                post_expecting_409(self.client, f"/api/coordinator/drafts/{d['draftId']}/approve", "approve",
                                   json={"version": d["version"]}, headers=hdr(self.token, str(uuid.uuid4())))


@events.test_stop.add_listener
def audit(environment, **_):
    """Assert no double bookings straight from the database."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("AUDIT skipped: set DATABASE_URL to audit the DB")
        return
    import psycopg
    q = {
        "interviewer": """SELECT count(*) FROM interview_panel a JOIN interview_panel b
            ON a.interviewer_id = b.interviewer_id AND a.interview_id < b.interview_id AND a.booked AND b.booked
            AND tstzrange(a.start_ts, a.end_ts) && tstzrange(b.start_ts, b.end_ts)""",
        "room": """SELECT count(*) FROM interviews a JOIN interviews b ON a.room_id = b.room_id AND a.id < b.id
            AND a.status IN ('CONFIRMED','FLAGGED','COMPLETED') AND b.status IN ('CONFIRMED','FLAGGED','COMPLETED')
            AND tstzrange(a.start_ts, a.end_ts) && tstzrange(b.start_ts, b.end_ts)""",
        "student": """SELECT count(*) FROM interviews a JOIN interviews b ON a.student_id = b.student_id AND a.id < b.id
            AND a.status IN ('CONFIRMED','FLAGGED','COMPLETED') AND b.status IN ('CONFIRMED','FLAGGED','COMPLETED')
            AND tstzrange(a.start_ts, a.end_ts) && tstzrange(b.start_ts, b.end_ts)""",
    }
    with psycopg.connect(url) as conn:
        for name, sql in q.items():
            n = conn.execute(sql).fetchone()[0]
            print(f"AUDIT double-booked {name}s: {n}")
            if n:
                environment.process_exit_code = 1
