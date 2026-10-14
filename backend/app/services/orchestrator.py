"""Queue coordination. PostgreSQL remains the source of truth for task state."""

import json
import logging
import time
import uuid
from datetime import timedelta

from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import DELAYED_KEY, QUEUE_KEY, TERMINAL_TASK_STATUSES, event_channel, queue_marker
from app.errors import AppError
from app.metrics import queue_depth
from app.models import Agent, DeadLetter, Task
from app.redis_client import get_redis
from app.services.activity import record_activity
from app.timeutils import as_utc, utcnow

logger = logging.getLogger(__name__)


def build_input_text(data: dict) -> str:
    parts: list[str] = []
    for key in ("text", "message", "prompt", "title"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        parts.append(json.dumps(data, default=str))
    return " ".join(parts)[:4000]


def publish_task(task: Task) -> None:
    payload = json.dumps({"task_id": task.id, "status": task.status})
    try:
        client = get_redis()
        client.publish(event_channel(task.id), payload)
        from app.constants import dashboard_cache_key

        client.delete(dashboard_cache_key(task.owner_id))
    except RedisError:
        logger.exception("failed to publish task event", extra={"task_id": task.id})


def refresh_queue_depth() -> int:
    try:
        depth = int(get_redis().llen(QUEUE_KEY))
    except RedisError:
        logger.exception("failed to read queue depth")
        return -1
    queue_depth.set(depth)
    return depth


def enqueue_now(task_id: str) -> None:
    client = get_redis()
    marker = queue_marker(task_id)
    acquired = client.set(marker, "1", nx=True, ex=30)
    if not acquired:
        return
    try:
        client.lpush(QUEUE_KEY, task_id)
    except RedisError:
        client.delete(marker)
        raise
    refresh_queue_depth()


def schedule_task(task_id: str, when_timestamp: float) -> None:
    get_redis().zadd(DELAYED_KEY, {task_id: when_timestamp})


def pop_task(timeout: int | None = None) -> str | None:
    client = get_redis()
    if timeout is None:
        task_id = client.rpop(QUEUE_KEY)
    else:
        item = client.brpop(QUEUE_KEY, timeout=timeout)
        task_id = item[1] if item else None
    if task_id:
        client.delete(queue_marker(task_id))
        refresh_queue_depth()
    return task_id


def promote_due_tasks() -> int:
    client = get_redis()
    now = time.time()
    due = client.zrangebyscore(DELAYED_KEY, "-inf", now)
    moved = 0
    for task_id in due:
        if client.zrem(DELAYED_KEY, task_id):
            enqueue_now(task_id)
            moved += 1
    return moved


def backoff_seconds(attempt: int) -> float:
    settings = get_settings()
    exponent = max(attempt - 1, 0)
    delay = min(settings.retry_max_seconds, settings.retry_base_seconds * (2**exponent))
    return float(delay)


def _find_existing(db: Session, owner_id: str, idempotency_key: str) -> Task | None:
    return db.scalar(select(Task).where(Task.owner_id == owner_id, Task.idempotency_key == idempotency_key))


def _queue_pending(db: Session, task: Task) -> None:
    enqueue_now(task.id)
    task.status = "queued"
    task.queued_at = utcnow()
    task.scheduled_at = task.queued_at
    task.updated_at = task.queued_at
    db.commit()
    db.refresh(task)
    publish_task(task)


def create_task(
    db: Session,
    agent: Agent,
    owner_id: str,
    payload: dict,
    idempotency_key: str | None,
    title: str | None,
) -> tuple[Task, bool]:
    key = idempotency_key or uuid.uuid4().hex
    existing = _find_existing(db, owner_id, key)
    if existing:
        if existing.status == "pending":
            try:
                _queue_pending(db, existing)
            except RedisError as exc:
                raise AppError(
                    "dependency_unavailable",
                    "Task was saved but the queue is unavailable. Retry with the same idempotency key.",
                    503,
                    details={"task_id": existing.id},
                ) from exc
        return existing, False

    text = build_input_text(payload)
    task = Task(
        agent_id=agent.id,
        owner_id=owner_id,
        idempotency_key=key,
        title=(title or text[:80] or agent.name)[:200],
        input=payload,
        input_text=text,
        status="pending",
        attempt=0,
        max_retries=agent.max_retries,
        dead_letter=False,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _find_existing(db, owner_id, key)
        if raced:
            return raced, False
        raise
    db.refresh(task)
    record_activity(
        db,
        owner_id,
        "task.created",
        f"Task queued for {agent.name}",
        agent_id=agent.id,
        task_id=task.id,
    )
    try:
        _queue_pending(db, task)
    except RedisError as exc:
        raise AppError(
            "dependency_unavailable",
            "Task was saved but the queue is unavailable. Retry with the same idempotency key.",
            503,
            details={"task_id": task.id},
        ) from exc
    return task, True


def mark_cancelled(db: Session, task: Task, reason: str = "Cancelled by user") -> Task:
    now = utcnow()
    task.status = "cancelled"
    task.error = reason
    task.finished_at = now
    task.updated_at = now
    task.lease_expires_at = None
    task.worker_id = None
    db.commit()
    db.refresh(task)
    publish_task(task)
    record_activity(db, task.owner_id, "task.cancelled", reason, agent_id=task.agent_id, task_id=task.id)
    return task


def fail_task(db: Session, task: Task, reason: str, dead_letter: bool) -> Task:
    now = utcnow()
    task.status = "failed"
    task.error = reason[:4000]
    task.dead_letter = dead_letter
    task.finished_at = now
    task.updated_at = now
    task.lease_expires_at = None
    task.worker_id = None
    db.commit()
    if dead_letter:
        db.add(
            DeadLetter(
                task_id=task.id,
                owner_id=task.owner_id,
                reason=task.error,
                payload={
                    "input": task.input,
                    "error": task.error,
                    "attempt": task.attempt,
                    "agent_id": task.agent_id,
                },
            )
        )
        db.commit()
    db.refresh(task)
    publish_task(task)
    record_activity(
        db,
        task.owner_id,
        "task.failed",
        task.error or "Task failed",
        agent_id=task.agent_id,
        task_id=task.id,
        details={"dead_letter": dead_letter, "attempt": task.attempt},
    )
    return task


def schedule_retry(db: Session, task: Task, reason: str) -> Task:
    task.attempt += 1
    task.error = reason[:4000]
    task.updated_at = utcnow()
    task.worker_id = None
    task.lease_expires_at = None
    if task.attempt > task.max_retries:
        return fail_task(db, task, reason, dead_letter=True)
    delay = backoff_seconds(task.attempt)
    when = utcnow() + timedelta(seconds=delay)
    task.status = "queued"
    task.scheduled_at = when
    task.finished_at = None
    db.commit()
    db.refresh(task)
    try:
        schedule_task(task.id, time.time() + delay)
    except RedisError:
        logger.exception("failed to schedule retry for %s", task.id)
    publish_task(task)
    record_activity(
        db,
        task.owner_id,
        "task.retry_scheduled",
        f"Retry scheduled in {delay:.1f}s after attempt {task.attempt}",
        agent_id=task.agent_id,
        task_id=task.id,
    )
    return task


def manual_retry(db: Session, task: Task) -> Task:
    if task.status != "failed":
        raise AppError("invalid_state", "Only failed tasks can be retried", 409)
    now = utcnow()
    task.status = "queued"
    task.dead_letter = False
    task.error = None
    task.finished_at = None
    task.cancel_requested = False
    task.attempt = 0
    task.worker_id = None
    task.lease_expires_at = None
    task.scheduled_at = now
    task.queued_at = now
    task.updated_at = now
    letters = db.scalars(select(DeadLetter).where(DeadLetter.task_id == task.id, DeadLetter.resolved_at.is_(None))).all()
    for letter in letters:
        letter.resolved_at = now
    db.commit()
    try:
        enqueue_now(task.id)
    except RedisError as exc:
        raise AppError("dependency_unavailable", "Queue is unavailable", 503) from exc
    db.refresh(task)
    publish_task(task)
    record_activity(db, task.owner_id, "task.retried", "Task requeued by user", agent_id=task.agent_id, task_id=task.id)
    return task


def reconcile_queued_tasks() -> int:
    """Requeue durable tasks that never reached Redis or whose marker expired."""
    db_session = None
    from app.database import SessionLocal

    db_session = SessionLocal()
    moved = 0
    try:
        now = utcnow()
        tasks = db_session.scalars(
            select(Task).where(Task.status.in_(["pending", "queued"]), Task.cancel_requested.is_(False))
        ).all()
        for task in tasks:
            scheduled = as_utc(task.scheduled_at)
            try:
                if task.status == "queued" and scheduled and scheduled > now:
                    schedule_task(task.id, scheduled.timestamp())
                    continue
                if task.status == "pending":
                    _queue_pending(db_session, task)
                else:
                    enqueue_now(task.id)
                moved += 1
            except RedisError:
                logger.exception("reconcile failed for task %s", task.id)
        return moved
    finally:
        db_session.close()


def recover_expired_leases() -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    recovered = 0
    try:
        now = utcnow()
        tasks = db.scalars(select(Task).where(Task.status == "running")).all()
        for task in tasks:
            lease = as_utc(task.lease_expires_at)
            if lease and lease > now:
                continue
            if task.cancel_requested:
                mark_cancelled(db, task, "Cancelled while the worker lease was expired")
                continue
            task.status = "queued"
            task.worker_id = None
            task.lease_expires_at = None
            task.error = "Recovered after the worker lease expired"
            task.updated_at = now
            task.scheduled_at = now
            db.commit()
            try:
                enqueue_now(task.id)
            except RedisError:
                logger.exception("failed to requeue recovered task %s", task.id)
                continue
            publish_task(task)
            record_activity(
                db,
                task.owner_id,
                "task.recovered",
                "Task requeued after a worker lease expired",
                agent_id=task.agent_id,
                task_id=task.id,
            )
            recovered += 1
        return recovered
    finally:
        db.close()


def claim_task(db: Session, task_id: str) -> tuple[Task, str] | None:
    from sqlalchemy import update

    task = db.get(Task, task_id)
    if task is None or task.status in TERMINAL_TASK_STATUSES:
        return None
    if task.cancel_requested and task.status in {"pending", "queued"}:
        mark_cancelled(db, task)
        return None
    agent = db.get(Agent, task.agent_id)
    timeout = agent.timeout_seconds if agent else 60
    token = str(uuid.uuid4())
    now = utcnow()
    lease = now + timedelta(seconds=timeout)
    result = db.execute(
        update(Task)
        .where(Task.id == task_id)
        .where(
            or_(
                Task.status.in_(["pending", "queued"]),
                Task.status == "running",
            )
        )
        .where(or_(Task.status != "running", Task.lease_expires_at.is_(None), Task.lease_expires_at < now))
        .values(
            status="running",
            worker_id=token,
            lease_expires_at=lease,
            updated_at=now,
        )
    )
    db.commit()
    db.expire_all()
    claimed = db.get(Task, task_id)
    if claimed is None or claimed.worker_id != token or claimed.status != "running":
        return None
    if claimed.started_at is None:
        claimed.started_at = now
        claimed.updated_at = now
        db.commit()
        db.refresh(claimed)
    publish_task(claimed)
    return claimed, token
