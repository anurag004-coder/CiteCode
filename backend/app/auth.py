import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import HTTPException, Request, Response

from . import db
from .config import SESSION_COOKIE_SECURE, SESSION_TTL_DAYS


SESSION_COOKIE = "cw_session"
DEMO_EMAIL = "example123@gmail.com"
DEMO_PASSWORD = "Admin@123"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_demo_user() -> Dict:
    user_id = str(uuid.uuid4())
    created_at = _now().isoformat()
    # The mock login validates the fixed demo pair directly; this column is unused by it.
    user = db.create_user(user_id, DEMO_EMAIL, "mock-demo-account", created_at)
    if user is None:
        existing = db.get_user_by_email(DEMO_EMAIL)
        if existing is None:
            raise HTTPException(status_code=500, detail="Could not initialize the demo account.")
        return db.get_user_by_id(existing["id"])
    return user


def authenticate_demo(email: str, password: str) -> Dict:
    email_matches = hmac.compare_digest(email.encode("utf-8"), DEMO_EMAIL.encode("utf-8"))
    password_matches = hmac.compare_digest(password.encode("utf-8"), DEMO_PASSWORD.encode("utf-8"))
    if not email_matches or not password_matches:
        raise HTTPException(status_code=401, detail="Use the prefilled demo email and password.")
    user = db.get_user_by_email(DEMO_EMAIL)
    if user is None:
        return _create_demo_user()
    return db.get_user_by_id(user["id"])


def set_session_cookie(response: Response, user_id: str) -> None:
    now = _now()
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
    db.create_session(_token_digest(token), user_id, now.isoformat(), expires_at.isoformat())
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(_token_digest(token))
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def get_current_user(request: Request) -> Dict:
    token: Optional[str] = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    user = db.get_session_user(_token_digest(token), _now().isoformat())
    if user is None:
        raise HTTPException(status_code=401, detail="Your session expired. Please sign in again.")
    return user
