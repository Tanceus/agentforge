import json
import re
import time

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import TERMINAL_TASK_STATUSES, event_channel
from app.database import SessionLocal, get_db
from app.deps import get_current_user, get_owned_agent, get_owned_task
from app.errors import AppError
from app.models import Agent, Task, TaskStep, User
from app.redis_client import get_redis
from app.schemas.common import Page
from app.schemas.task import StepOut, TaskCreate, TaskDetail, TaskOut
from app.security.rate_limit import enforce_rate_limit
from app.services.orchestrator import create_task, manual_retry, mark_cancelled
from app.timeutils import utcnow

router = APIRouter(tags=["tasks"])
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")


def _limit(user: User, scope: str = "api") -> None:
    settings = get_settings()
    limit = settings.task_rate_limit_per_minute if scope == "tasks" else settings.rate_limit_per_minute
    enforce_rate_limit(user.id, scope, limit)


def _detail(db: Session, task: Task) -> TaskDetail:
    steps = db.scalars(select(TaskStep).where(TaskStep.task_id == task.id).order_by(TaskStep.step_index)).all()
    agent = db.get(Agent, task.agent_id)
    detail = TaskDetail.model_validate(task)
    detail.steps = [StepOut.model_validate(step) for step in steps]
    detail.agent_name = agent.name if agent else None
    return detail


@router.post("/agents/{agent_id}/tasks", response_model=TaskDetail, status_code=201)
def enqueue_agent_task(
    agent_id: str,
    payload: TaskCreate,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskDetail:
    _limit(user, "tasks")
    agent = get_owned_agent(db, user, agent_id)
    if agent.status != "active":
        raise AppError("agent_not_active", "Start the agent before running tasks", 409)
    key = idempotency_key or payload.idempotency_key
    if key and not IDEMPOTENCY_RE.match(key):
        raise AppError("validation_error", "Idempotency key must be 8-200 characters of letters, numbers, ., _, :, or -", 422)
    task, created = create_task(db, agent, user.id, payload.input, key, payload.title)
    response.status_code = 201 if created else 200
    if not created:
        response.headers["Idempotency-Replayed"] = "true"
    return _detail(db, task)


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(
    q: str | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    dead_letter: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    _limit(user)
    filters = [Task.owner_id == user.id]
    if status:
        if status not in {"pending", "queued", "running", "completed", "failed", "cancelled"}:
            raise AppError("validation_error", "Unknown task status", 422)
        filters.append(Task.status == status)
    if agent_id:
        filters.append(Task.agent_id == agent_id)
    if dead_letter is not None:
        filters.append(Task.dead_letter.is_(dead_letter))
    if q:
        like = f"%{q.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Task.title).like(like),
                func.lower(Task.input_text).like(like),
                func.lower(func.coalesce(Task.error, "")).like(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(Task).where(*filters)) or 0
    rows = db.scalars(
        select(Task).where(*filters).order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(items=[TaskOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskDetail:
    _limit(user)
    task = get_owned_task(db, user, task_id)
    return _detail(db, task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskDetail)
def cancel_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskDetail:
    _limit(user)
    task = get_owned_task(db, user, task_id)
    if task.status in TERMINAL_TASK_STATUSES:
        raise AppError("invalid_state", "Task is already finished", 409)
    if task.status == "running":
        task.cancel_requested = True
        task.updated_at = utcnow()
        db.commit()
        db.refresh(task)
    else:
        task.cancel_requested = True
        mark_cancelled(db, task)
    return _detail(db, task)


@router.post("/tasks/{task_id}/retry", response_model=TaskDetail)
def retry_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TaskDetail:
    _limit(user, "tasks")
    task = get_owned_task(db, user, task_id)
    manual_retry(db, task)
    db.refresh(task)
    return _detail(db, task)


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, user: User = Depends(get_current_user)) -> StreamingResponse:
    _limit(user)

    def generate():
        last = None
        started = time.time()
        pubsub = None
        try:
            pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(event_channel(task_id))
        except Exception:
            pubsub = None
        try:
            while time.time() - started < 120:
                db = SessionLocal()
                try:
                    task = db.get(Task, task_id)
                    if task is None or task.owner_id != user.id:
                        yield 'event: error\ndata: {"error":"not_found"}\n\n'
                        return
                    payload = _detail(db, task).model_dump(mode="json")
                finally:
                    db.close()
                encoded = json.dumps(payload)
                if encoded != last:
                    yield f"event: task\ndata: {encoded}\n\n"
                    last = encoded
                if payload["status"] in TERMINAL_TASK_STATUSES:
                    return
                if pubsub is not None:
                    try:
                        pubsub.get_message(timeout=1.0)
                    except Exception:
                        time.sleep(0.5)
                else:
                    time.sleep(0.5)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
