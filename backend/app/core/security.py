"""
Security utilities: password hashing and JWT access/refresh token handling.
"""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
from jose import jwt

from app.core.config import settings

# bcrypt only reads the first 72 bytes. passlib truncated silently, so every
# stored hash was made from the truncated prefix; bcrypt>=5 raises instead.
# Truncating here keeps those hashes verifiable and long passwords a non-error.
_BCRYPT_MAX_BYTES = 72


def _bcrypt_input(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(_bcrypt_input(plain_password), hashed_password.encode("ascii"))


# Verified against when the email is unknown, so "no such user" costs the same
# bcrypt time as "wrong password" and response time doesn't reveal which it was.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password")


def _create_token(subject: UUID, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        # Unique per call: `iat`/`exp` only have second resolution, so two
        # tokens issued for the same user within the same second (common in
        # fast test suites) would otherwise be byte-identical and collide on
        # the refresh_tokens.token_hash unique constraint.
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID) -> str:
    return _create_token(
        user_id,
        timedelta(minutes=settings.access_token_expire_minutes),
        token_type="access",
    )


def create_refresh_token(user_id: UUID) -> str:
    return _create_token(
        user_id,
        timedelta(days=settings.refresh_token_expire_days),
        token_type="refresh",
    )


def create_approval_token(user_id: UUID) -> str:
    # Goes in the email to the admin. Its own `type` keeps it from being
    # accepted as an access/refresh token (and the other way round).
    return _create_token(
        user_id,
        timedelta(days=settings.approval_token_expire_days),
        token_type="approval",
    )


class TokenPayload:
    def __init__(self, user_id: UUID, token_type: str):
        self.user_id = user_id
        self.token_type = token_type


def decode_token(token: str, expected_type: str) -> TokenPayload:
    """
    Raises jose.JWTError (or ValueError for a type mismatch) on any problem —
    callers turn that into a 401 at the API boundary, not here, so this stays
    reusable outside of FastAPI's request/response cycle.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require_exp": True},
    )
    token_type = payload.get("type")
    if token_type != expected_type:
        raise ValueError(f"Expected a {expected_type} token, got {token_type}")
    return TokenPayload(user_id=UUID(payload["sub"]), token_type=token_type)
