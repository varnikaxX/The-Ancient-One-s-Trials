"""psycopg v3 pool + plain-SQL helpers. No ORM.

    with transaction() as conn:          # commits on success, rolls back on error
        conn.execute("UPDATE ...", (..,))
        row = conn.execute("SELECT ...").fetchone()   # rows are dicts
"""
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.config import settings

_pool = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                p = ConnectionPool(
                    settings.database_url,
                    min_size=settings.db_pool_min,
                    max_size=settings.db_pool_max,
                    kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"},
                    open=False,
                )
                p.open(wait=True, timeout=15)
                _pool = p
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction():
    """One pooled connection == one transaction (commit on exit, rollback on exception)."""
    with get_pool().connection() as conn:
        yield conn


def fetchone(sql, params=None):
    with transaction() as conn:
        return conn.execute(sql, params).fetchone()


def fetchall(sql, params=None):
    with transaction() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql, params=None):
    with transaction() as conn:
        conn.execute(sql, params)


def jsonb(obj):
    return Jsonb(obj)


def iso(dt):
    """datetime -> '2026-11-03T09:00:00Z' (contract time format)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"bad ISO-8601 timestamp: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_integrity_error(exc: BaseException) -> bool:
    """Unique / exclusion violations (SQLSTATE 23505 / 23P01)."""
    return isinstance(exc, (psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation))
