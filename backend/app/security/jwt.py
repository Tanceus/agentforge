import uuid
from datetime import timedelta
from typing import Any

import jwt

from app.config import get_settings
from app.errors import AppError
from app.timeutils import utcnow


def _encode(payload: dict[str, Any]) -> str:
    settings = get_settings()
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def create_access_token(user_id: str, role: str) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
    }
    return _encode(payload)


def create_refresh_token(user_id: str) -> tuple[str, str]:
    settings = get_settings()
    now = utcnow()
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.refresh_token_days)).timestamp()),
    }
    return _encode(payload), jti


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AppError("unauthorized", "Invalid or expired token", 401) from exc
    if not isinstance(payload, dict) or "sub" not in payload:
        raise AppError("unauthorized", "Invalid or expired token", 401)
    return payload
