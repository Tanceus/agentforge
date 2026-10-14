"""Execute queued tasks. Importing this module does not start the loop."""

import logging
import time
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import CancelledError, LostLeaseError, PermanentError, TransientError
from app.metrics import dead_letters_total, task_duration_seconds, tasks_total
from app.models import Agent, Task
from app.services.executor import execute_agent
from app.services.orchestrator import (
    claim_task,
    fail_task,
    mark_cancelled,
    pop_task,
    promote_due_tasks,
    publish_task,
    reconcile_queued_tasks,
    recover_expired_leases,
    schedule_retry,
)
from app.services.activity import record_activity
from app.timeutils import as_utc, utcnow

logger = logging.getLogger(__name__)
WORKER_ID = str(uuid.uuid4())


def _still_owner(db: Session, task_id: str, token: str) -> Task | None:
    task = db.get(Task, task_id)
    if task is None:
        return None
    db.refresh(task)
    if task.worker_id != token or task.status != "running":
        return None
    return task


def _observe(task: Task) -> None:
    started = as_utc(task.started_at)
    finished = as_utc(task.finished_at)
    if started and finished:
        task_duration_seconds.observe(max((finished - started).total_seconds(), 0))


def _complete(db: Session, task: Task, token: str, result: dict) -> None:
    owned = _still_owner(db, task.id, token)
    if owned is None:
        return
    now = utcnow()
    updated = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.worker_id == token, Task.status == "running")
        .values(
            status="completed",
            result=result,
            error=None,
            finished_at=now,
            updated_at=now,
            lease_expires_at=None,
            worker_id=None,
            dead_letter=False,
        )
    )
    db.commit()
    db.expire_all()
    fresh = db.get(Task, task.id)
    if fresh is None or fresh.status != "completed":
        return
    publish_task(fresh)
    record_activity(
        db,
        fresh.owner_id,
        "task.completed",
        "Task completed",
        agent_id=fresh.agent_id,
        task_id=fresh.id,
    )
    tasks_total.labels(status="completed").inc()
    _observe(fresh)


def process_task(task_id: str) -> None:
    db = SessionLocal()
    try:
        claimed = claim_task(db, task_id)
        if claimed is None:
            return
        task, token = claimed
        agent = db.get(Agent, task.agent_id)
        if agent is None:
            fail_task(db, task, "Agent no longer exists", dead_letter=True)
            tasks_total.labels(status="failed").inc()
            dead_letters_total.inc()
            return
        try:
            result = execute_agent(db, task, agent, token)
        except LostLeaseError:
            logger.info("worker lost the lease for task %s", task_id)
            return
        except CancelledError:
            owned = _still_owner(db, task.id, token)
            if owned is None:
                return
            mark_cancelled(db, owned, "Cancelled during execution")
            tasks_total.labels(status="cancelled").inc()
            return
        except TransientError as exc:
            owned = _still_owner(db, task.id, token)
            if owned is None:
                return
            updated = schedule_retry(db, owned, str(exc))
            if updated.dead_letter:
                tasks_total.labels(status="failed").inc()
                dead_letters_total.inc()
                _observe(updated)
            else:
                tasks_total.labels(status="retry").inc()
            return
        except PermanentError as exc:
            owned = _still_owner(db, task.id, token)
            if owned is None:
                return
            failed = fail_task(db, owned, str(exc), dead_letter=True)
            tasks_total.labels(status="failed").inc()
            dead_letters_total.inc()
            _observe(failed)
            return
        except Exception:
            logger.exception("unexpected failure while executing task %s", task_id)
            owned = _still_owner(db, task.id, token)
            if owned is None:
                return
            updated = schedule_retry(db, owned, "Unexpected worker error")
            if updated.dead_letter:
                tasks_total.labels(status="failed").inc()
                dead_letters_total.inc()
            return
        _complete(db, task, token, result)
    finally:
        db.close()


def process_available(max_tasks: int = 50) -> int:
    """Drain currently due work. Used by tests and the demo seed."""
    processed = 0
    idle_rounds = 0
    while processed < max_tasks and idle_rounds < 2:
        promote_due_tasks()
        task_id = pop_task(timeout=None)
        if not task_id:
            idle_rounds += 1
            continue
        idle_rounds = 0
        process_task(task_id)
        processed += 1
    return processed


def heartbeat() -> None:
    from app.config import get_settings
    from app.constants import worker_key
    from app.metrics import active_workers
    from app.redis_client import get_redis

    settings = get_settings()
    client = get_redis()
    client.setex(worker_key(WORKER_ID), settings.worker_heartbeat_seconds, utcnow().isoformat())
    count = sum(1 for _ in client.scan_iter("agentforge:worker:*", count=100))
    active_workers.set(count)


def main() -> None:
    from app.config import get_settings
    from app.logging_config import configure_logging
    from prometheus_client import start_http_server

    settings = get_settings()
    configure_logging(settings.log_level)
    start_http_server(settings.worker_metrics_port)
    logger.info("agentforge worker started")
    while True:
        try:
            heartbeat()
            recover_expired_leases()
            reconcile_queued_tasks()
            promote_due_tasks()
            task_id = pop_task(timeout=2)
            if task_id:
                process_task(task_id)
        except KeyboardInterrupt:
            logger.info("worker stopping")
            return
        except Exception:
            logger.exception("worker loop error")
            time.sleep(1)


if __name__ == "__main__":
    main()
