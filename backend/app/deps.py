"""
Shared FastAPI dependencies: DB session and current-authenticated-user.
"""

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import SessionLocal  # your sessionmaker, wired to settings.database_url
from app.models import User

# auto_error=False: lets us raise 401 ourselves when no credentials are sent,
# instead of HTTPBearer's default 403 for a missing Authorization header.
# Both "no token" and "bad token" should look the same to the client (401),
# so callers don't need to distinguish the two cases.
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except (JWTError, ValueError):
        # `from None`, not `from exc`: the 401 is deliberate and identical
        # for every decode failure, and chaining the JWT error would leak
        # which part of the token was wrong into logs and tracebacks.
        raise credentials_exception from None

    user = db.get(User, payload.user_id)
    if user is None:
        raise credentials_exception
    return user