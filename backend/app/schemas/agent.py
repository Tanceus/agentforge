from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.constants import ALLOWED_TOOLS
from app.schemas.common import ORMModel


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(min_length=1, max_length=8000)
    tools: list[str] = Field(min_length=1, max_length=4)
    provider: str | None = None
    model: str | None = Field(default=None, max_length=120)
    max_retries: int = Field(default=2, ge=0, le=10)
    timeout_seconds: int = Field(default=60, ge=5, le=300)

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: list[str]) -> list[str]:
        unknown = [tool for tool in value if tool not in ALLOWED_TOOLS]
        if unknown:
            raise ValueError(f"Unsupported tools: {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("Duplicate tools are not allowed")
        return value

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if value not in {"mock", "openai"}:
            raise ValueError("provider must be mock or openai")
        return value


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    tools: list[str] | None = Field(default=None, min_length=1, max_length=4)
    provider: str | None = None
    model: str | None = Field(default=None, max_length=120)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    timeout_seconds: int | None = Field(default=None, ge=5, le=300)

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return AgentCreate.validate_tools(value)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        return AgentCreate.validate_provider(value)


class AgentOut(ORMModel):
    id: str
    owner_id: str
    name: str
    description: str
    system_prompt: str
    provider: str | None
    model: str | None
    tools: list[str]
    status: str
    max_retries: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
