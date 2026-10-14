import json

from fastapi import APIRouter, Depends, Query
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import dashboard_cache_key
from app.database import get_db, ping_database
from app.deps import get_current_user, require_admin
from app.models import Activity, Agent, DeadLetter, StoredRecord, Task, User
from app.redis_client import get_redis, ping_redis
from app.schemas.common import Page
from app.schemas.dashboard import ActivityOut, AdminOverview, DashboardOut, DeadLetterOut, RecordOut, SystemStatus
from app.schemas.task import TaskOut
from app.security.rate_limit import enforce_rate_limit
from app.services.orchestrator import refresh_queue_depth

router = APIRouter(tags=["dashboard"])

TASK_STATUSES = ("pending", "queued", "running", "completed", "failed", "cancelled")
AGENT_STATUSES = ("draft", "active", "paused")


def _limit(user: User) -> None:
    enforce_rate_limit(user.id, "api", get_settings().rate_limit_per_minute)


def system_status() -> SystemStatus:
    settings = get_settings()
    database = "ok"
    redis_status = "ok"
    depth = 0
    workers = 0
    try:
        ping_database()
    except Exception:
        database = "unavailable"
    try:
        ping_redis()
        depth = max(refresh_queue_depth(), 0)
        workers = sum(1 for _ in get_redis().scan_iter("agentforge:worker:*", count=100))
    except RedisError:
        redis_status = "unavailable"
        depth = -1
        workers = 0
    return SystemStatus(
        api="ok",
        database=database,
        redis=redis_status,
        queue_depth=depth,
        active_workers=workers,
        llm_provider=settings.llm_provider,
    )


def _dashboard(db: Session, user: User) -> DashboardOut:
    task_counts = {status: 0 for status in TASK_STATUSES}
    rows = db.execute(
        select(Task.status, func.count()).where(Task.owner_id == user.id).group_by(Task.status)
    ).all()
    for status, count in rows:
        if status in task_counts:
            task_counts[status] = int(count)
    agent_counts = {status: 0 for status in AGENT_STATUSES}
    agent_rows = db.execute(
        select(Agent.status, func.count())
        .where(Agent.owner_id == user.id, Agent.status != "archived")
        .group_by(Agent.status)
    ).all()
    for status, count in agent_rows:
        if status in agent_counts:
            agent_counts[status] = int(count)
    activity = db.scalars(
        select(Activity).where(Activity.owner_id == user.id).order_by(Activity.created_at.desc()).limit(10)
    ).all()
    tasks = db.scalars(
        select(Task).where(Task.owner_id == user.id).order_by(Task.created_at.desc()).limit(8)
    ).all()
    return DashboardOut(
        tasks_by_status=task_counts,
        agents_by_status=agent_counts,
        recent_activity=[ActivityOut.model_validate(row) for row in activity],
        recent_tasks=[TaskOut.model_validate(row) for row in tasks],
        system=system_status(),
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardOut:
    _limit(user)
    settings = get_settings()
    cache_key = dashboard_cache_key(user.id)
    if settings.dashboard_cache_seconds > 0:
        try:
            cached = get_redis().get(cache_key)
            if cached:
                return DashboardOut.model_validate(json.loads(cached))
        except (RedisError, ValueError):
            pass
    payload = _dashboard(db, user)
    if settings.dashboard_cache_seconds > 0:
        try:
            get_redis().setex(cache_key, settings.dashboard_cache_seconds, payload.model_dump_json())
        except RedisError:
            pass
    return payload


@router.get("/activity", response_model=Page[ActivityOut])
def list_activity(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[ActivityOut]:
    _limit(user)
    filters = [Activity.owner_id == user.id]
    total = db.scalar(select(func.count()).select_from(Activity).where(*filters)) or 0
    rows = db.scalars(
        select(Activity)
        .where(*filters)
        .order_by(Activity.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(items=[ActivityOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size)


@router.get("/records", response_model=Page[RecordOut])
def list_records(
    collection: str | None = None,
    task_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[RecordOut]:
    _limit(user)
    filters = [StoredRecord.owner_id == user.id]
    if collection:
        filters.append(StoredRecord.collection == collection)
    if task_id:
        filters.append(StoredRecord.task_id == task_id)
    total = db.scalar(select(func.count()).select_from(StoredRecord).where(*filters)) or 0
    rows = db.scalars(
        select(StoredRecord)
        .where(*filters)
        .order_by(StoredRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(items=[RecordOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size)


@router.get("/dead-letters", response_model=Page[DeadLetterOut])
def list_dead_letters(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[DeadLetterOut]:
    _limit(user)
    filters = [DeadLetter.owner_id == user.id, DeadLetter.resolved_at.is_(None)]
    total = db.scalar(select(func.count()).select_from(DeadLetter).where(*filters)) or 0
    rows = db.scalars(
        select(DeadLetter)
        .where(*filters)
        .order_by(DeadLetter.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page(items=[DeadLetterOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size)


@router.get("/admin/overview", response_model=AdminOverview)
def admin_overview(user: User = Depends(require_admin), db: Session = Depends(get_db)) -> AdminOverview:
    _limit(user)
    return AdminOverview(
        users=db.scalar(select(func.count()).select_from(User)) or 0,
        agents=db.scalar(select(func.count()).select_from(Agent)) or 0,
        tasks=db.scalar(select(func.count()).select_from(Task)) or 0,
        dead_letters=db.scalar(
            select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved_at.is_(None))
        )
        or 0,
    )
