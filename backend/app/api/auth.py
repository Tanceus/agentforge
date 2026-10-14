from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import refresh_key
from app.database import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import User
from app.redis_client import get_redis
from app.schemas.auth import (
    LoginRequest,
    PasswordChange,
    ProfileUpdate,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.security.jwt import create_access_token, create_refresh_token, decode_token
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import client_ip, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user: User) -> TokenResponse:
    settings = get_settings()
    access = create_access_token(user.id, user.role)
    refresh, jti = create_refresh_token(user.id)
    get_redis().setex(refresh_key(jti), settings.refresh_token_seconds, user.id)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    enforce_rate_limit(client_ip(request), "register-ip", settings.login_rate_limit_per_minute)
    email = payload.email.lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise AppError("conflict", "An account with that email already exists", 409)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _issue_tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    email = payload.email.lower()
    enforce_rate_limit(email, "login", settings.login_rate_limit_per_minute)
    enforce_rate_limit(client_ip(request), "login-ip", settings.login_rate_limit_per_minute)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise AppError("unauthorized", "Invalid email or password", 401)
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    decoded = decode_token(payload.refresh_token)
    if decoded.get("type") != "refresh" or not decoded.get("jti"):
        raise AppError("unauthorized", "Invalid or expired token", 401)
    key = refresh_key(str(decoded["jti"]))
    stored = get_redis().get(key)
    if stored != decoded.get("sub"):
        raise AppError("unauthorized", "Invalid or expired token", 401)
    get_redis().delete(key)
    user = db.get(User, decoded["sub"])
    if user is None or not user.is_active:
        raise AppError("unauthorized", "Invalid or expired token", 401)
    return _issue_tokens(user)


@router.post("/logout", status_code=204)
def logout(payload: RefreshRequest) -> Response:
    decoded = decode_token(payload.refresh_token)
    jti = decoded.get("jti")
    if jti:
        get_redis().delete(refresh_key(str(jti)))
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    enforce_rate_limit(user.id, "api", get_settings().rate_limit_per_minute)
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    enforce_rate_limit(user.id, "api", get_settings().rate_limit_per_minute)
    user.full_name = payload.full_name.strip()
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    enforce_rate_limit(user.id, "api", get_settings().rate_limit_per_minute)
    if not verify_password(payload.current_password, user.password_hash):
        raise AppError("unauthorized", "Current password is incorrect", 401)
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return Response(status_code=204)
