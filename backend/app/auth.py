import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import Cookie, Header, HTTPException, Request


COOKIE_NAME = "hr_session"
_login_attempts: dict[str, list[float]] = {}
_attempt_lock = threading.Lock()


def login_allowed(client_ip: str) -> bool:
    now = time.time()
    with _attempt_lock:
        recent = [stamp for stamp in _login_attempts.get(client_ip, []) if now - stamp < 300]
        _login_attempts[client_ip] = recent
        return len(recent) < 5


def failed_login(client_ip: str):
    with _attempt_lock:
        _login_attempts.setdefault(client_ip, []).append(time.time())


def successful_login(client_ip: str):
    with _attempt_lock:
        _login_attempts.pop(client_ip, None)


def _secret() -> bytes:
    value = os.getenv("HR_SESSION_SECRET")
    if not value:
        # Process-local secret is safe for a local demo; sessions expire on restart.
        global _fallback_secret
        try:
            return _fallback_secret
        except NameError:
            _fallback_secret = secrets.token_bytes(32)
            return _fallback_secret
    return value.encode()


def check_password(candidate: str) -> bool:
    expected = os.getenv("HR_ADMIN_PASSWORD")
    if not expected:
        return False
    return hmac.compare_digest(hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(expected.encode()).digest())


def create_session() -> tuple[str, str]:
    expires = str(int(time.time()) + 8 * 3600)
    csrf = secrets.token_urlsafe(24)
    data = f"{expires}.{csrf}"
    signature = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{signature}", csrf


def require_hr(request: Request, hr_session: str | None = Cookie(default=None)) -> str:
    if not hr_session:
        raise HTTPException(401, "请先登录 HR 后台")
    try:
        expires, csrf, signature = hr_session.split(".", 2)
        expected = hmac.new(_secret(), f"{expires}.{csrf}".encode(), hashlib.sha256).hexdigest()
        if int(expires) < time.time() or not hmac.compare_digest(signature, expected):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(401, "HR 会话已失效") from None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf):
            raise HTTPException(403, "CSRF 校验失败")
    return csrf
