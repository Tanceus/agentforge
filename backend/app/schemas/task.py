import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class TaskCreate(BaseModel):
    input: dict[str, Any]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200, pattern=r"^[A-Za-z0-9._:-]+$")
    title: str | None = Field(default=None, max_length=200)

    @field_validator("input")
    @classmethod
    def limit_input(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("input must be a non-empty object")
        encoded = json.dumps(value, default=str)
        if len(encoded) > 32_000:
            raise ValueError("input is too large")
        return value


class StepOut(ORMModel):
    id: str
    step_index: int
    kind: str
    name: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class TaskOut(ORMModel):
    id: str
    agent_id: str
    owner_id: str
    idempotency_key: str
    title: str
    input: dict
    status: str
    result: dict | None
    error: str | None
    attempt: int
    max_retries: int
    dead_letter: bool
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class TaskDetail(TaskOut):
    steps: list[StepOut] = []
    agent_name: str | None = None
