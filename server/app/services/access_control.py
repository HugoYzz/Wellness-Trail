"""单用户访问控制：PBKDF2 PIN、短期内存会话与登录限流。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import User

COOKIE_NAME = "kangji_session"
PIN_ITERATIONS = 310_000
MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW_SECONDS = 5 * 60
LOCAL_USERNAME = "local"

_sessions: dict[str, float] = {}
_failed_logins: dict[str, list[float]] = {}
_lock = threading.Lock()


def _local_user(db: Session) -> User:
    user = db.scalars(select(User).order_by(User.id)).first()
    if user is None:
        user = User(username=LOCAL_USERNAME, settings_json={})
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def validate_pin(pin: str) -> None:
    if not pin.isdigit() or not 6 <= len(pin) <= 12:
        raise ValueError("PIN 必须是 6-12 位数字")


def hash_pin(pin: str, *, salt: bytes | None = None) -> str:
    validate_pin(pin)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS
    )
    return f"pbkdf2_sha256${PIN_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, rounds, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            pin.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(rounds),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (TypeError, ValueError):
        return False


def pin_is_configured(db: Session) -> bool:
    return bool(_local_user(db).password_hash)


def configure_pin(db: Session, pin: str) -> None:
    user = _local_user(db)
    if user.password_hash:
        raise ValueError("访问 PIN 已设置")
    user.password_hash = hash_pin(pin)
    db.add(user)
    db.commit()


def authenticate_pin(db: Session, pin: str) -> bool:
    return verify_pin(pin, _local_user(db).password_hash)


def _prune_sessions(now: float) -> None:
    expired = [token for token, expires_at in _sessions.items() if expires_at <= now]
    for token in expired:
        _sessions.pop(token, None)


def create_session() -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    ttl = max(1, config.KANGJI_SESSION_HOURS) * 60 * 60
    now = time.time()
    with _lock:
        _prune_sessions(now)
        _sessions[token] = now + ttl
    return token, ttl


def session_is_valid(token: str | None) -> bool:
    if not token:
        return False
    now = time.time()
    with _lock:
        _prune_sessions(now)
        expires_at = _sessions.get(token)
        return expires_at is not None and expires_at > now


def session_expires_at(token: str | None) -> str | None:
    if not token:
        return None
    with _lock:
        expires_at = _sessions.get(token)
    if not expires_at or expires_at <= time.time():
        return None
    return datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        _sessions.pop(token, None)


def login_retry_after(client_id: str) -> int:
    now = time.time()
    with _lock:
        recent = [
            attempted
            for attempted in _failed_logins.get(client_id, [])
            if attempted > now - FAILED_WINDOW_SECONDS
        ]
        _failed_logins[client_id] = recent
        if len(recent) < MAX_FAILED_ATTEMPTS:
            return 0
        return max(1, int(recent[0] + FAILED_WINDOW_SECONDS - now))


def record_failed_login(client_id: str) -> None:
    now = time.time()
    with _lock:
        recent = [
            attempted
            for attempted in _failed_logins.get(client_id, [])
            if attempted > now - FAILED_WINDOW_SECONDS
        ]
        recent.append(now)
        _failed_logins[client_id] = recent


def clear_failed_logins(client_id: str) -> None:
    with _lock:
        _failed_logins.pop(client_id, None)
