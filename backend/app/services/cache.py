"""Redis helpers: slot-list cache + per-user pub/sub for SSE. Redis trouble never breaks the API:
every call degrades gracefully (cache miss / dropped live event; the DB stays the source of truth)."""
import json
import logging

import redis

from app.config import settings

log = logging.getLogger("trials.cache")
_client = None


def get_redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    return _client


def slots_key(company_id: int, round_no: int) -> str:
    return f"slots:{company_id}:{round_no}"


def cache_get(key: str):
    try:
        raw = get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        log.warning("cache get failed: %s", exc)
        return None


def cache_set(key: str, value, ttl: int = None):
    try:
        get_redis().set(key, json.dumps(value), ex=ttl or settings.cache_ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache set failed: %s", exc)


def invalidate_company_slots(company_id):
    """Called on availability change and on booking commit."""
    if company_id is None:
        return
    try:
        get_redis().delete(*[slots_key(company_id, r) for r in (1, 2, 3)])
    except Exception as exc:  # noqa: BLE001
        log.warning("cache invalidate failed: %s", exc)


def user_channel(user_id: int) -> str:
    return f"user:{user_id}"


def publish_user(user_id: int, type_: str, payload: dict):
    try:
        get_redis().publish(user_channel(user_id), json.dumps({"type": type_, "payload": payload}))
    except Exception as exc:  # noqa: BLE001
        log.warning("publish failed: %s", exc)
