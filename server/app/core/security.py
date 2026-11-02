"""Password hashing and JWT access and refresh tokens."""

import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .settings import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _encode(claims: dict, lifetime_seconds: float) -> str:
    now = time.time()
    payload = {**claims, "iat": int(now), "exp": int(now + lifetime_seconds)}
    return jwt.encode(payload, get_settings().token_secret(), algorithm="HS256")


def create_access_token(user_id: str, role: str, team_id: str | None) -> str:
    claims = {"sub": user_id, "role": role, "team": team_id, "type": "access"}
    return _encode(claims, get_settings().access_token_minutes * 60)


def create_refresh_token(user_id: str) -> tuple[str, str, float]:
    """Returns (token, jti, expires_at). The jti is stored so organisers can revoke it."""
    jti = uuid.uuid4().hex
    lifetime = get_settings().refresh_token_hours * 3600
    return _encode({"sub": user_id, "jti": jti, "type": "refresh"}, lifetime), jti, time.time() + lifetime


def decode_token(token: str, expected_type: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().token_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == expected_type else None
