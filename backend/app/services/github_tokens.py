"""Stored GitHub credentials: save, hand out a valid access token, and drop revoked ones.

Tokens never leave the backend. Access and refresh tokens are Fernet-encrypted at rest. A user
token close to expiry is renewed with its refresh token; GitHub rotates the refresh token on every
use, so the row is locked while renewing to stop two processes spending the same one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations import github
from app.models import AuditEvent, GitHubAccount, utcnow

RENEW_BEFORE = timedelta(minutes=5)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite returns naive datetimes


def store(acct: GitHubAccount, tokens: github.TokenSet) -> None:
    acct.encrypted_token = encrypt_secret(tokens.access_token)
    acct.encrypted_refresh_token = encrypt_secret(tokens.refresh_token) if tokens.refresh_token else None
    acct.token_expires_at = tokens.expires_at
    acct.refresh_expires_at = tokens.refresh_expires_at


def forget(db: Session, acct: GitHubAccount, reason: str) -> None:
    """Remove a connection GitHub no longer honours, so the UI shows "disconnected"."""
    db.add(AuditEvent(user_id=acct.user_id, action="github.revoked", detail={"reason": reason}))
    db.delete(acct)
    db.commit()


def disconnect(db: Session, acct: GitHubAccount, settings: Settings) -> bool:
    """End a GitHub connection: delete DevPilot's copy first, then ask GitHub to revoke the grant.

    The local delete is committed before any network call, so a GitHub outage can never leave
    DevPilot holding usable credentials. Returns True only if GitHub confirmed the revocation."""
    token: str | None
    refresh: str | None
    try:
        token = decrypt_secret(acct.encrypted_token)
        refresh = decrypt_secret(acct.encrypted_refresh_token) if acct.encrypted_refresh_token else None
    except ValueError:  # undecryptable (secret key changed): nothing usable to revoke with
        token = refresh = None
    expired = acct.token_expires_at is not None and _aware(acct.token_expires_at) <= utcnow()
    refresh_ok = acct.refresh_expires_at is None or _aware(acct.refresh_expires_at) > utcnow()
    user_id = acct.user_id
    db.delete(acct)
    db.add(AuditEvent(user_id=user_id, action="github.disconnect"))
    db.commit()

    if not token or not settings.github_configured:
        revoked = False
    else:
        if expired and refresh and refresh_ok:
            # GitHub needs a live token to identify the grant; a fresh one is used once, never stored.
            try:
                token = github.refresh_tokens(settings, refresh, utcnow()).access_token
            except github.GitHubError:
                pass  # try with the old token; GitHub decides
        revoked = github.revoke_grant(settings, token)
    db.add(AuditEvent(user_id=user_id, action="github.grant_revoke", detail={"revoked": revoked}))
    db.commit()
    return revoked


def access_token(db: Session, acct: GitHubAccount, settings: Settings) -> str:
    """A usable access token for this account, renewing it first when it is about to expire."""
    if acct.token_expires_at is None or _aware(acct.token_expires_at) - RENEW_BEFORE > utcnow():
        return decrypt_secret(acct.encrypted_token)
    db.refresh(acct, with_for_update=True)  # another process may have renewed it meanwhile
    if acct.token_expires_at is not None and _aware(acct.token_expires_at) - RENEW_BEFORE > utcnow():
        return decrypt_secret(acct.encrypted_token)
    expired = acct.refresh_expires_at is not None and _aware(acct.refresh_expires_at) <= utcnow()
    if not acct.encrypted_refresh_token or expired:
        forget(db, acct, "expired")
        raise github.GitHubError("Your GitHub authorization expired. Connect GitHub again.", 401)
    try:
        tokens = github.refresh_tokens(settings, decrypt_secret(acct.encrypted_refresh_token), utcnow())
    except github.GitHubError as e:
        if e.status == 503:  # GitHub unreachable: keep the connection, let the caller retry
            raise
        forget(db, acct, "refresh_rejected")
        raise github.GitHubError("GitHub rejected the stored authorization. Connect GitHub again.", 401) from e
    store(acct, tokens)
    db.commit()
    return tokens.access_token
