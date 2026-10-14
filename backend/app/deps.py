import logging

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError, not_found
from app.models import Agent, Task, User
from app.security.jwt import decode_token

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError("unauthorized", "Authentication is required", 401)
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AppError("unauthorized", "Invalid or expired token", 401)
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AppError("unauthorized", "Invalid or expired token", 401)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AppError("forbidden", "Admin access is required", 403)
    return user


def get_owned_agent(db: Session, user: User, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.owner_id != user.id or agent.status == "archived":
        raise not_found("Agent")
    return agent


def get_owned_task(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.owner_id != user.id:
        raise not_found("Task")
    return task


def owned_agent_query(user: User):
    return select(Agent).where(Agent.owner_id == user.id, Agent.status != "archived")
