"""Shared test fixtures (unittest only). Needs PostgreSQL (+ optional Redis).

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trials_test   (DESTROYED and recreated per run!)
    REDIS_URL=redis://localhost:6379/1

Run from backend/:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trials_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ["CELERY_EAGER"] = "true"          # tasks run inline: no worker needed
os.environ["USE_STUB_SOLVER"] = os.environ.get("USE_STUB_SOLVER", "true")
os.environ["EMAIL_DRY_RUN"] = "true"
os.environ["RESEND_API_KEY"] = ""
os.environ["SENDGRID_API_KEY"] = ""

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PASSWORD = "Passw0rd!"


def reset_database():
    """Fresh schema + seed. Refuses to run unless the DB name ends with _test."""
    url = os.environ["DATABASE_URL"]
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise RuntimeError(f"refusing to wipe database {name!r}: test DB names must end with _test")
    from db import migrate  # noqa: WPS433
    migrate.DATABASE_URL = url
    from app import db as appdb
    appdb.close_pool()
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        migrate.main(["--reset", "--seed"])
    try:                                                   # slot ids restart at 1 -> stale cache would lie
        from app.services import cache
        cache.get_redis().flushdb()
    except Exception:  # noqa: BLE001
        pass


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def day(offset_days=3, hour=9):
    d = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_database()
        from app.main import app
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    def setUp(self):
        reset_database()                                   # every test starts from a clean seeded DB

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    # helpers ---------------------------------------------------------------
    def key(self):
        return str(uuid.uuid4())

    def login(self, email, password=PASSWORD):
        r = self.client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    def h(self, token, key=None):
        h = {"Authorization": f"Bearer {token}"}
        if key is not False:
            h["Idempotency-Key"] = key or self.key()
        return h

    def register(self, n):
        email = f"s{n}_{uuid.uuid4().hex[:6]}@t.test"
        r = self.client.post("/api/auth/register", json={
            "name": f"Student {n}", "email": email, "password": PASSWORD, "regNo": f"R{n}{uuid.uuid4().hex[:5]}",
            "branch": "CSE", "skills": ["Coding"]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"], r.json()["user"]["id"]

    def set_availability(self, token, start, hours=2):  # hours may be 0.5
        r = self.client.put("/api/interviewer/availability", headers=self.h(token, False),
                            json={"slots": [{"start": ts(start), "end": ts(start + timedelta(hours=hours))}]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def sql(self, query, params=None):
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
            cur = c.execute(query, params)
            return cur.fetchall() if cur.description else None
