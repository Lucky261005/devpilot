import hmac
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db, serialize
from app.core.security import account_key, hash_password, hash_token, ip_key, new_session_token, verify_password
from app.models import AuditEvent, IpRateEvent, LoginAttempt, User, UserSession, utcnow
from app.schemas import Credentials, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_TTL = timedelta(days=7)
# Per-account sign-in throttle: at most this many failed attempts per account in a rolling window.
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
THROTTLED = "Too many failed sign-in attempts for this account. Try again in 15 minutes."
# Per client IP, separately for sign-in and registration: accepted requests per sliding window.
IP_LIMIT = 10
IP_WINDOW = timedelta(seconds=60)
# Verifying against a real hash for unknown emails keeps login timing uniform.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def _start_session(db: Session, user: User, response: Response) -> None:
    token = new_session_token()
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + SESSION_TTL))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def _throttle(db: Session, request: Request, action: str) -> None:
    """At most IP_LIMIT accepted `action` requests per client IP per sliding IP_WINDOW, shared by
    every API process through the database. Requests for one IP and action are serialized, so the
    count and the insert are one step; a refused request leaves no record, so it uses no slot."""
    key = ip_key(request.client.host if request.client else "?")
    serialize(db, ip_key(f"{action}:{key}"))
    now = utcnow()
    mine = (IpRateEvent.scope == action) & (IpRateEvent.ip_key == key)
    db.query(IpRateEvent).filter(mine, IpRateEvent.expires_at <= now).delete()
    if db.query(func.count(IpRateEvent.id)).filter(mine, IpRateEvent.expires_at > now).scalar() >= IP_LIMIT:
        db.commit()  # keeps the expired-row cleanup, releases the lock
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a minute.")
    db.add(IpRateEvent(scope=action, ip_key=key, expires_at=now + IP_WINDOW))
    db.commit()


# Same answer for a new and an already-registered email, so registration cannot be used to find
# out who has an account. No session is started; the client signs in next.
REGISTERED = {"detail": "If this email was not already registered, the account was created. Sign in to continue."}


def _check_registration_policy(settings: Settings, supplied: str | None) -> None:
    mode = settings.registration_mode
    if mode == "closed":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed on this server.")
    if mode == "invite":
        configured = settings.invite_code
        if not configured:  # fail closed: an unset code must never accept an empty one
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Registration is by invitation, and this server has no invite code set."
            )
        if not supplied or not hmac.compare_digest(supplied.encode(), configured.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "A valid invite code is required to create an account.")


@router.post("/register", status_code=202)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    _throttle(db, request, "register")
    _check_registration_policy(get_settings(), body.invite_code)
    email = body.email.lower()
    password_hash = hash_password(body.password)  # hashed either way, so timing does not differ
    existing = db.query(User).filter_by(email=email).first()
    if existing is not None:
        db.add(AuditEvent(user_id=existing.id, action="user.register_existing_email"))
    else:
        user = User(email=email, password_hash=password_hash)
        db.add(user)
        db.flush()
        db.add(AuditEvent(user_id=user.id, action="user.register"))
    db.commit()
    return REGISTERED


def _reserve_login_attempt(db: Session, key: str) -> LoginAttempt:
    """Admit this attempt only if fewer than LOGIN_FAILURE_LIMIT are recorded in the window, and
    record it. Attempts for one account are serialized, so the count and the insert are one step:
    a PostgreSQL advisory lock per account key (held until commit, shared by every API process),
    and on SQLite the opening DELETE takes the database write lock. Exactly LOGIN_FAILURE_LIMIT
    attempts per window are checked against the password; refused ones leave no record."""
    serialize(db, key)
    now = utcnow()
    cutoff = now - LOGIN_FAILURE_WINDOW
    db.query(LoginAttempt).filter(LoginAttempt.account_key == key, LoginAttempt.created_at <= cutoff).delete()
    recent = (
        db.query(func.count(LoginAttempt.id))
        .filter(LoginAttempt.account_key == key, LoginAttempt.created_at > cutoff)
        .scalar()
    )
    if recent >= LOGIN_FAILURE_LIMIT:
        db.commit()  # keeps the expired-row cleanup, releases the lock
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, THROTTLED)
    attempt = LoginAttempt(account_key=key, created_at=now)
    db.add(attempt)
    db.commit()
    return attempt


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    _throttle(db, request, "login")
    email = body.email.strip().lower()
    key = account_key(email)
    # Throttled by email whether or not the account exists, so the 429 reveals nothing.
    _reserve_login_attempt(db, key)
    user = db.query(User).filter_by(email=email).one_or_none()
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")  # attempt kept
    db.query(LoginAttempt).filter_by(account_key=key).delete()  # success clears earlier failures
    db.add(AuditEvent(user_id=user.id, action="user.login"))
    _start_session(db, user, response)
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response, db: Session = Depends(get_db), token: str | None = Cookie(default=None, alias=SESSION_COOKIE)
):
    if token:
        db.query(UserSession).filter_by(token_hash=hash_token(token)).delete()
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
