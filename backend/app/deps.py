"""FastAPI dependencies: auth, role guards, idempotency."""
from typing import Callable, Optional

from fastapi import Depends, Header, Request

from app import db
from app.errors import ApiError
from app.security import decode_token


def _bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _load_user(token: Optional[str]) -> dict:
    if not token:
        raise ApiError("UNAUTHORIZED", "Missing bearer token")
    claims = decode_token(token)
    row = db.fetchone("SELECT id, name, email, role FROM users WHERE id = %s", (int(claims["sub"]),))
    if not row:
        raise ApiError("UNAUTHORIZED", "Unknown user")
    return row


def current_user(request: Request) -> dict:
    return _load_user(_bearer(request))


def current_user_or_query_token(request: Request) -> dict:
    """For browser features that cannot set headers (EventSource, plain <a download>):
    also accepts ?token=<JWT>. Used only by GET /events and the .ics download."""
    return _load_user(_bearer(request) or request.query_params.get("token"))


def require_role(*roles: str) -> Callable:
    """Server-side role guard: `user = Depends(require_role("STUDENT"))`."""

    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise ApiError("FORBIDDEN", "Your role cannot do this")
        return user

    return dep


def idempotency_key(idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> str:
    if not idempotency_key or not idempotency_key.strip():
        raise ApiError("VALIDATION", "Idempotency-Key header is required on write requests")
    if len(idempotency_key) > 200:
        raise ApiError("VALIDATION", "Idempotency-Key is too long")
    return idempotency_key.strip()


STALE_CLAIM_SECONDS = 30


def run_idempotent(user_id: int, scope: str, key: str, fn: Callable[[], object]):
    """Invariant 5. Run fn() at most once per (user, endpoint, key); replay the stored response afterwards.

    Claim-then-run: the key row is INSERTed first (ON CONFLICT DO NOTHING), so of any number of concurrent
    retries exactly one owns the work. No pooled connection is held while fn() runs (fn opens its own
    transaction), so a burst of requests can never exhaust the pool. A failed fn() releases the claim so a
    retry re-executes; a claim older than STALE_CLAIM_SECONDS (crashed worker) can be taken over."""
    import time
    full = f"{user_id}:{scope}:{key}"
    claim = {"status": 0, "body": None, "state": "IN_PROGRESS"}
    deadline = time.monotonic() + STALE_CLAIM_SECONDS
    while True:
        with db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO idempotency_keys (key, response) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING RETURNING key",
                (full, db.jsonb(claim))).fetchone()
            if row:
                break                                                     # we own it
            existing = conn.execute(
                "SELECT response, now() - created_at AS age FROM idempotency_keys WHERE key = %s", (full,)).fetchone()
            if existing is None:
                continue                                                  # released between the two statements
            resp = existing["response"]
            if resp.get("state") != "IN_PROGRESS":
                return resp["body"]
            if existing["age"].total_seconds() > STALE_CLAIM_SECONDS:     # crashed owner: take over
                conn.execute("DELETE FROM idempotency_keys WHERE key = %s", (full,))
                continue
        if time.monotonic() > deadline:
            raise ApiError("VALIDATION", "A request with this Idempotency-Key is still being processed")
        time.sleep(0.05)
    try:
        body = fn()
    except BaseException:
        db.execute("DELETE FROM idempotency_keys WHERE key = %s", (full,))
        raise
    db.execute("UPDATE idempotency_keys SET response = %s WHERE key = %s",
               (db.jsonb({"status": 200, "body": body, "state": "DONE"}), full))
    return body
