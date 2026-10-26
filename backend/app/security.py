"""argon2 password hashing + PyJWT tokens."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import settings
from app.errors import ApiError

# OWASP Password Storage Cheat Sheet minimum for argon2id (19 MiB, t=2, p=1). ~8x cheaper than argon2-cffi's
# defaults, which matters in a registration/login rush on a small box. Old hashes keep verifying because the
# parameters are stored inside each hash.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user_id: int, role: str, minutes: int = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=minutes if minutes is not None else settings.jwt_expiry_minutes)
    return jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError:
        raise ApiError("UNAUTHORIZED", "Session expired, please log in again")
    except jwt.PyJWTError:
        raise ApiError("UNAUTHORIZED", "Invalid token")
