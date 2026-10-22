from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.models import AuditEvent, User, UserSession, utcnow
from app.schemas import Credentials, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_TTL = timedelta(days=7)
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


def _throttle(request: Request, action: str) -> None:
    ip = request.client.host if request.client else "?"
    if not limiter.allow((action, ip), limit=10, window_s=60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in a minute.")


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    _throttle(request, "register")
    email = body.email.lower()
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(AuditEvent(user_id=user.id, action="user.register"))
    _start_session(db, user, response)
    return user


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    _throttle(request, "login")
    user = db.query(User).filter_by(email=body.email.lower()).one_or_none()
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
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
