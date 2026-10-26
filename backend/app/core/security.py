"""Password hashing, session tokens and at-rest encryption for third-party tokens."""

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Session tokens are high-entropy, so a fast hash is sufficient (no need for argon2).
    return hashlib.sha256(token.encode()).hexdigest()


def account_key(email: str) -> str:
    """Keyed hash of a normalized email, used to throttle sign-ins without storing the email.

    Keyed with DEVPILOT_SECRET_KEY (required outside development) so stored keys cannot be
    reversed by hashing a list of candidate emails."""
    secret = (get_settings().secret_key or "devpilot-development-only").encode()
    return hmac.new(secret, b"login:" + email.strip().lower().encode(), hashlib.sha256).hexdigest()


def ip_key(ip: str) -> str:
    """Keyed hash of a client IP, so per-IP limits never store the address. Same key as account_key:
    without DEVPILOT_SECRET_KEY the small IPv4 space could otherwise be hashed and matched."""
    secret = (get_settings().secret_key or "devpilot-development-only").encode()
    return hmac.new(secret, b"ip:" + ip.strip().lower().encode(), hashlib.sha256).hexdigest()


def _fernet() -> Fernet:
    key = get_settings().secret_key
    if not key:
        # Development fallback: deterministic key derived from a constant. Never used in prod
        # because get_settings() refuses to start without DEVPILOT_SECRET_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(b"devpilot-dev-only").digest()).decode()
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored credential cannot be decrypted (secret key changed?)") from e
