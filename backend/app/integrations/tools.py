"""Allowlisted tools. Model output is validated here and never executed as code."""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import PermanentError, TransientError
from app.models import StoredRecord
from app.security.ssrf import SSRFError, validate_url

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "your",
    "have",
    "was",
    "are",
    "but",
    "not",
    "you",
    "our",
    "its",
}
URGENCY_KEYWORDS = ("urgent", "critical", "asap", "emergency", "outage", "sev-1", "sev1")


class PermanentToolError(PermanentError):
    pass


class TransientToolError(TransientError):
    pass


@dataclass
class ToolContext:
    db: Session
    owner_id: str
    agent_id: str
    task_id: str


class TextTransformArgs(BaseModel):
    operation: str
    text: str = Field(max_length=20_000)
    max_length: int | None = Field(default=None, ge=1, le=20_000)
    keyword_limit: int = Field(default=8, ge=1, le=20)

    @field_validator("operation")
    @classmethod
    def known_operation(cls, value: str) -> str:
        allowed = {
            "uppercase",
            "lowercase",
            "trim",
            "truncate",
            "word_count",
            "slugify",
            "extract_keywords",
            "classify_urgency",
        }
        if value not in allowed:
            raise ValueError(f"Unsupported text operation: {value}")
        return value


class HttpArgs(BaseModel):
    method: str
    url: str = Field(min_length=1, max_length=2000)
    body: str | None = Field(default=None, max_length=100_000)
    content_type: str | None = Field(default=None, max_length=100)

    @field_validator("method")
    @classmethod
    def known_method(cls, value: str) -> str:
        method = value.upper()
        if method not in {"GET", "POST", "HEAD"}:
            raise ValueError("HTTP method must be GET, POST, or HEAD")
        return method

    @field_validator("content_type")
    @classmethod
    def safe_content_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "\n" in value or "\r" in value or ":" in value:
            raise ValueError("Invalid content type")
        return value


class BranchArgs(BaseModel):
    left: Any
    op: str
    right: Any
    then_value: Any
    else_value: Any

    @field_validator("op")
    @classmethod
    def known_op(cls, value: str) -> str:
        if value not in {"eq", "neq", "gt", "lt", "gte", "lte", "contains"}:
            raise ValueError("Unsupported branch operator")
        return value


class StoreArgs(BaseModel):
    collection: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    data: dict[str, Any]


def _json_size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def _depth(value: Any, level: int = 0) -> int:
    if isinstance(value, dict):
        if not value:
            return level
        return max(_depth(item, level + 1) for item in value.values())
    if isinstance(value, list):
        if not value:
            return level
        return max(_depth(item, level + 1) for item in value)
    return level


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80]


def _keywords(text: str, limit: int) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    seen: list[str] = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _classify(text: str) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in URGENCY_KEYWORDS):
        return "high"
    return "normal"


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def run_text_transform(args: TextTransformArgs) -> dict[str, Any]:
    text = args.text
    operation = args.operation
    if operation == "uppercase":
        result: Any = text.upper()
    elif operation == "lowercase":
        result = text.lower()
    elif operation == "trim":
        result = text.strip()
    elif operation == "truncate":
        if not args.max_length:
            raise PermanentToolError("truncate requires max_length")
        result = text[: args.max_length]
    elif operation == "word_count":
        result = len([part for part in text.split() if part])
    elif operation == "slugify":
        result = _slugify(text)
    elif operation == "extract_keywords":
        result = _keywords(text, args.keyword_limit)
    elif operation == "classify_urgency":
        result = _classify(text)
    else:
        raise PermanentToolError("Unsupported text operation")
    return {"operation": operation, "result": result, "text_preview": text[:200]}


def _compare(args: BranchArgs) -> bool:
    left, right, op = args.left, args.right, args.op
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
    if op == "contains":
        return str(right) in str(left)
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is None or right_num is None:
        raise PermanentToolError("Numeric comparison requires numbers")
    if op == "gt":
        return left_num > right_num
    if op == "lt":
        return left_num < right_num
    if op == "gte":
        return left_num >= right_num
    if op == "lte":
        return left_num <= right_num
    raise PermanentToolError("Unsupported branch operator")


def run_branch(args: BranchArgs) -> dict[str, Any]:
    if _json_size({"left": args.left, "right": args.right, "then": args.then_value, "else": args.else_value}) > 20_000:
        raise PermanentToolError("Branch payload is too large")
    matched = _compare(args)
    value = args.then_value if matched else args.else_value
    return {"branch": "then" if matched else "else", "value": value, "op": args.op}


def run_store(args: StoreArgs, ctx: ToolContext) -> dict[str, Any]:
    if _depth(args.data) > 8 or _json_size(args.data) > 100_000:
        raise PermanentToolError("Record payload is too large")
    record = StoredRecord(
        owner_id=ctx.owner_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        collection=args.collection,
        data=args.data,
    )
    ctx.db.add(record)
    ctx.db.commit()
    ctx.db.refresh(record)
    return {"collection": args.collection, "record_id": record.id, "stored": True}


def safe_fetch(
    method: str,
    url: str,
    body: str | None = None,
    content_type: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    owns_client = client is None
    http = client or httpx.Client(timeout=settings.http_tool_timeout_seconds, follow_redirects=False)
    current = url
    try:
        for hop in range(4):
            validate_url(current)
            headers = {"user-agent": "AgentForge/1.0"}
            content = None
            request_method = method if hop == 0 else "GET"
            if hop == 0 and body is not None and method == "POST":
                content = body.encode("utf-8")
                headers["content-type"] = content_type or "application/json"
            try:
                response = http.request(request_method, current, content=content, headers=headers)
            except httpx.TimeoutException as exc:
                raise TransientToolError("HTTP request timed out") from exc
            except httpx.HTTPError as exc:
                raise TransientToolError("HTTP request failed") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise PermanentToolError("Redirect is missing a location")
                current = urljoin(str(response.url), location)
                continue
            raw = response.content[: settings.http_tool_max_bytes]
            text = raw.decode("utf-8", errors="replace")
            return {
                "status_code": response.status_code,
                "url": str(response.url),
                "body": text[:4000],
                "truncated": len(response.content) > settings.http_tool_max_bytes,
            }
        raise PermanentToolError("Too many redirects")
    finally:
        if owns_client:
            http.close()


def run_tool(name: str, arguments: dict[str, Any], ctx: ToolContext, http_client: httpx.Client | None = None) -> dict[str, Any]:
    try:
        if name == "text_transform":
            return run_text_transform(TextTransformArgs.model_validate(arguments))
        if name == "branch":
            return run_branch(BranchArgs.model_validate(arguments))
        if name == "store_record":
            return run_store(StoreArgs.model_validate(arguments), ctx)
        if name == "http_request":
            parsed = HttpArgs.model_validate(arguments)
            try:
                return safe_fetch(parsed.method, parsed.url, parsed.body, parsed.content_type, client=http_client)
            except SSRFError as exc:
                raise PermanentToolError(str(exc)) from exc
        raise PermanentToolError(f"Tool '{name}' is not allowed")
    except ValidationError as exc:
        raise PermanentToolError(f"Invalid arguments for {name}") from exc
    except (PermanentToolError, TransientToolError):
        raise
    except SSRFError as exc:
        raise PermanentToolError(str(exc)) from exc
