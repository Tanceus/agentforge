from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.task import TaskOut


class ActivityOut(ORMModel):
    id: str
    owner_id: str
    agent_id: str | None
    task_id: str | None
    event_type: str
    message: str
    details: dict
    created_at: datetime


class RecordOut(ORMModel):
    id: str
    owner_id: str
    agent_id: str | None
    task_id: str | None
    collection: str
    data: dict
    created_at: datetime


class DeadLetterOut(ORMModel):
    id: str
    task_id: str
    owner_id: str
    reason: str
    payload: dict
    created_at: datetime
    resolved_at: datetime | None


class SystemStatus(BaseModel):
    api: str
    database: str
    redis: str
    queue_depth: int
    active_workers: int
    llm_provider: str


class DashboardOut(BaseModel):
    tasks_by_status: dict[str, int]
    agents_by_status: dict[str, int]
    recent_activity: list[ActivityOut]
    recent_tasks: list[TaskOut]
    system: SystemStatus


class AdminOverview(BaseModel):
    users: int
    agents: int
    tasks: int
    dead_letters: int
