"""
Auth endpoints: register, login, refresh, logout, me.

Refresh tokens are stored hashed in the DB (see RefreshToken model) so
`/auth/logout` performs a real revocation, not just a client-side forget.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.deps import get_current_user, get_db
from app.models import User
from app.models.refresh_token import RefreshToken
from app.schemas import (
    PasswordChangeRequest,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserUpdate,
)
from app.schemas import (
    User as UserSchema,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _hash_token(token: str) -> str:
    # Refresh tokens are opaque JWTs already; we only need a fast, deterministic
    # hash to look them up / revoke them without storing the raw value.
    return sha256(token.encode()).hexdigest()


def _store_refresh_token(db: Session, user_id, token: str) -> None:
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(token),
            expires_at=expires_at,
        )
    )
    db.commit()


@router.post("/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        base_currency=payload.base_currency,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenPair:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        # Same error for "no such user" and "wrong password" — don't leak
        # which one it was.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _store_refresh_token(db, user.id, refresh_token)

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        token_data = decode_token(payload.refresh_token, expected_type="refresh")
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    token_hash = _hash_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if stored is None or stored.revoked_at is not None or stored.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked"
        )

    # Rotate: revoke the used refresh token and issue a new pair. This limits
    # the damage window if a refresh token is ever stolen (it's single-use).
    stored.revoked_at = datetime.now(UTC)

    new_access_token = create_access_token(token_data.user_id)
    new_refresh_token = create_refresh_token(token_data.user_id)
    _store_refresh_token(db, token_data.user_id, new_refresh_token)
    db.commit()

    return TokenPair(access_token=new_access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)) -> None:
    token_hash = _hash_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        db.commit()
    # Idempotent: logging out an already-revoked/unknown token still returns 204.


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserSchema)
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if payload.email is not None and payload.email != current_user.email:
        existing = db.query(User).filter(User.email == payload.email).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        current_user.email = payload.email

    if payload.base_currency is not None:
        current_user.base_currency = payload.base_currency

    # Anagrafica fields are nullable and independently clearable — a client
    # sends `null` explicitly to clear one without touching the others, so
    # these use exclude_unset rather than the `is not None` check above
    # (which would make "clear this field" indistinguishable from "leave it
    # alone").
    anagrafica_fields = payload.model_dump(
        exclude_unset=True, include={"first_name", "last_name", "date_of_birth"}
    )
    for field, value in anagrafica_fields.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password"
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
