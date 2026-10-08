"""
Auth endpoints: register, login, refresh, logout, me.

Refresh tokens are stored hashed in the DB (see RefreshToken model) so
`/auth/logout` performs a real revocation, not just a client-side forget.

Registration is gated by `settings.registration_mode`: in "approval" mode a new
account is `pending` until the admin follows the link emailed to them (the
`/auth/approvals/*` endpoints, authenticated by the token alone).
"""

import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_approval_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.deps import get_current_user, get_db
from app.models import Currency, User
from app.models.refresh_token import RefreshToken
from app.schemas import (
    ApprovalDecisionRequest,
    ApprovalRequestInfo,
    ApprovalTokenRequest,
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
from app.services.email import send_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Attempts per client IP and window; see core/rate_limit.py.
_LIMIT_REGISTER = Depends(rate_limit("register", 5, 3600))
_LIMIT_LOGIN = Depends(rate_limit("login", 10, 300))
_LIMIT_REFRESH = Depends(rate_limit("refresh", 60, 300))
_LIMIT_PASSWORD = Depends(rate_limit("password", 5, 600))
_LIMIT_APPROVAL = Depends(rate_limit("approval", 20, 600))


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


def _ensure_known_currency(db: Session, code: str) -> None:
    # An unknown code would reach the FK as a 500 and make up FX lookups.
    if db.get(Currency, code) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown currency {code!r}"
        )


def _notify_admin_of_registration(user_id: UUID, user_email: str) -> None:
    if not settings.admin_email:
        # Without this the account would sit pending with no one told.
        logger.warning("ADMIN_EMAIL is not set: %s is pending and nobody was notified", user_email)
        return
    token = create_approval_token(user_id)
    # The token rides in the URL fragment, which browsers never send to the
    # server: it stays out of the static host's access logs and Referer headers.
    link = f"{settings.frontend_base_url.rstrip('/')}/approvazione#token={token}"
    send_email(
        settings.admin_email,
        f"{settings.app_name}: nuova registrazione da approvare",
        f"{user_email} ha chiesto di registrarsi.\n\n"
        f"Approva o rifiuta da qui (valido {settings.approval_token_expire_days} giorni):\n"
        f"{link}\n",
    )


@router.post(
    "/register",
    response_model=UserSchema,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_LIMIT_REGISTER],
)
def register(
    payload: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> User:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    _ensure_known_currency(db, payload.base_currency)
    needs_approval = settings.registration_mode == "approval"
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        base_currency=payload.base_currency,
        approval_status="pending" if needs_approval else "approved",
        terms_accepted_at=datetime.now(UTC),
        terms_version=settings.terms_version,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent registrations passed the check above; the unique
        # index caught the second. Same answer as the check, not a 500.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    db.refresh(user)

    if needs_approval:
        background_tasks.add_task(_notify_admin_of_registration, user.id, user.email)
    return user


@router.post("/login", response_model=TokenPair, dependencies=[_LIMIT_LOGIN])
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenPair:
    user = db.query(User).filter(User.email == payload.email).first()
    password_ok = verify_password(
        payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH
    )
    if user is None or not password_ok:
        # Same error for "no such user" and "wrong password" — don't leak
        # which one it was.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    # Checked only after the password matched, so these distinct answers don't
    # reveal which emails exist to someone who doesn't know the password.
    if user.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "ACCOUNT_PENDING_APPROVAL"
                if user.approval_status == "pending"
                else "ACCOUNT_REJECTED"
            ),
        )

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _store_refresh_token(db, user.id, refresh_token)

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPair, dependencies=[_LIMIT_REFRESH])
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        token_data = decode_token(payload.refresh_token, expected_type="refresh")
    except (JWTError, ValueError):
        # `from None` for the same reason as deps.get_current_user: one
        # opaque 401 regardless of how the token was malformed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None

    token_hash = _hash_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if stored is None or stored.revoked_at is not None or stored.expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked"
        )

    user = db.get(User, token_data.user_id)
    if user is None or user.approval_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked"
        )

    # Rotate: revoke the used refresh token and issue a new pair. This limits
    # the damage window if a refresh token is ever stolen (it's single-use).
    # The conditional UPDATE is what makes it single-use under concurrency:
    # two requests can both pass the check above, but only one flips the row.
    claimed = (
        db.query(RefreshToken)
        .filter(RefreshToken.id == stored.id, RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": datetime.now(UTC)}, synchronize_session=False)
    )
    if claimed == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked"
        )

    new_access_token = create_access_token(token_data.user_id)
    new_refresh_token = create_refresh_token(token_data.user_id)
    _store_refresh_token(db, token_data.user_id, new_refresh_token)

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
        _ensure_known_currency(db, payload.base_currency)
        current_user.base_currency = payload.base_currency

    if payload.hide_amounts is not None:
        current_user.hide_amounts = payload.hide_amounts

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

    # Same: `null` switches the work section off.
    if "work_type" in payload.model_fields_set:
        current_user.work_type = payload.work_type.value if payload.work_type else None

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password", response_model=TokenPair, dependencies=[_LIMIT_PASSWORD])
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TokenPair:
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password"
        )
    current_user.password_hash = hash_password(payload.new_password)

    # A stolen password's sessions must not survive its replacement: revoke
    # every refresh token, then hand this device a fresh pair so the person
    # who just changed it isn't the one logged out.
    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(UTC)}, synchronize_session=False)
    access_token = create_access_token(current_user.id)
    refresh_token = create_refresh_token(current_user.id)
    _store_refresh_token(db, current_user.id, refresh_token)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


# ---------------------------------------------------------------------------
# Admin approval. No login: the signed token in the emailed link is the
# credential. Two steps (preview, then decision) because a GET that approves
# would be triggered by mail scanners and link previewers opening the URL.
# ---------------------------------------------------------------------------

def _user_from_approval_token(db: Session, token: str) -> User:
    try:
        token_data = decode_token(token, expected_type="approval")
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired link"
        ) from None
    user = db.get(User, token_data.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return user


@router.post(
    "/approvals/preview", response_model=ApprovalRequestInfo, dependencies=[_LIMIT_APPROVAL]
)
def preview_approval(
    payload: ApprovalTokenRequest, db: Session = Depends(get_db)
) -> User:
    return _user_from_approval_token(db, payload.token)


@router.post(
    "/approvals/decision", response_model=ApprovalRequestInfo, dependencies=[_LIMIT_APPROVAL]
)
def decide_approval(
    payload: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_approval_token(db, payload.token)
    # One decision per request: a link opened twice (or approve after reject)
    # must not silently flip an outcome the admin already chose.
    if user.approval_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Request already handled"
        )

    approved = payload.decision == "approve"
    user.approval_status = "approved" if approved else "rejected"
    db.commit()
    db.refresh(user)

    login_link = f"{settings.frontend_base_url.rstrip('/')}/login"
    if approved:
        background_tasks.add_task(
            send_email,
            user.email,
            f"{settings.app_name}: account approvato",
            f"Il tuo account è stato approvato. Puoi accedere da qui:\n{login_link}\n",
        )
    else:
        background_tasks.add_task(
            send_email,
            user.email,
            f"{settings.app_name}: registrazione non approvata",
            "La tua richiesta di registrazione non è stata approvata.\n",
        )
    return user
