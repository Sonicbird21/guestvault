from __future__ import annotations

import os
import time
import secrets
from collections import deque, defaultdict
from typing import Deque, Dict

from flask import session, request, abort


def require_admin() -> None:
    if not session.get("is_admin"):
        abort(403)


def generate_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token(token: str | None) -> None:
    if not token or token != session.get("csrf_token"):
        abort(400, description="Invalid CSRF token")


def validate_csrf_from_request() -> None:
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    validate_csrf_token(token)


class RateLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window = window_seconds
        self.buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.time()
        q = self.buckets[key]
        # prune
        while q and (now - q[0]) > self.window:
            q.popleft()
        if len(q) >= self.attempts:
            return False
        q.append(now)
        return True


def get_login_rate_limiter() -> RateLimiter:
    # Defaults gentle: 8 attempts per 5 minutes
    attempts = int(os.environ.get("LOGIN_LIMIT_ATTEMPTS") or os.environ.get("LOGIN_MAX_ATTEMPTS", "8"))
    window = int(os.environ.get("LOGIN_LIMIT_WINDOW") or os.environ.get("LOGIN_WINDOW_SECONDS", "300"))
    # Singleton per process
    global _LOGIN_LIMITER
    try:
        limiter = _LOGIN_LIMITER
    except NameError:
        _LOGIN_LIMITER = RateLimiter(attempts, window)
        limiter = _LOGIN_LIMITER
    return limiter
