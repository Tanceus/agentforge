"""LLM providers. The mock provider is deterministic and makes no network calls."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.constants import ALLOWED_TOOLS
from app.errors import PermanentError, TransientError

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "http_request": {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": "Fetch a public http or https URL. Private, loopback, link-local, and metadata addresses are blocked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "HEAD"]},
                    "url": {"type": "string"},
                    "body": {"type": "string"},
                    "content_type": {"type": "string"},
                },
                "required": ["method", "url"],
                "additionalProperties": False,
            },
        },
    },
    "text_transform": {
        "type": "function",
        "function": {
            "name": "text_transform",
            "description": "Transform text with a fixed operation such as trim, classify_urgency, word_count, or slugify.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "text": {"type": "string"},
                    "max_length": {"type": "integer"},
                    "keyword_limit": {"type": "integer"},
                },
                "required": ["operation", "text"],
                "additionalProperties": False,
            },
        },
    },
    "branch": {
        "type": "function",
        "function": {
            "name": "branch",
            "description": "Compare two values and return then_value or else_value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "left": {},
                    "op": {"type": "string"},
                    "right": {},
                    "then_value": {},
                    "else_value": {},
                },
                "required": ["left", "op", "right", "then_value", "else_value"],
            },
        },
    },
    "store_record": {
        "type": "function",
        "function": {
            "name": "store_record",
            "description": "Persist a JSON object in the caller's tenant collection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["collection", "data"],
                "additionalProperties": False,
            },
        },
    },
}


@dataclass
class LLMDecision:
    content: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    tool_call_id: str | None = None

    @property
    def is_final(self) -> bool:
        return self.tool_name is None


class TransientLLMError(TransientError):
    pass


def user_text_from_input(raw: dict[str, Any]) -> str:
    for key in ("text", "message", "prompt", "input"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return json.dumps(raw, default=str)[:2000]


def _tool_payloads(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content") or "{}"
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            parsed = {"raw": content}
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


class MockLLM:
    """Keyword and tool-list planner used for local tests and the demo agent."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[str],
        attempt: int,
        raw_input: dict[str, Any],
        model: str,
    ) -> LLMDecision:
        settings = get_settings()
        if settings.environment != "production":
            failures = raw_input.get("simulate_transient_failures") or 0
            try:
                failures = int(failures)
            except (TypeError, ValueError):
                failures = 0
            failures = max(0, min(failures, 10))
            if attempt <= failures:
                raise TransientLLMError("Simulated transient LLM failure")

        enabled = [tool for tool in tools if tool in ALLOWED_TOOLS]
        plan = self._plan(raw_input, enabled)
        done = _tool_payloads(messages)
        if len(done) >= len(plan):
            return LLMDecision(content=self._summary(raw_input, done))
        step = plan[len(done)]
        arguments = dict(step["arguments"])
        if step["name"] == "branch" and done:
            arguments["left"] = done[-1].get("result")
        if step["name"] == "store_record":
            arguments["data"] = self._record_data(raw_input, done)
        return LLMDecision(
            tool_name=step["name"],
            arguments=arguments,
            tool_call_id=f"call_{len(done) + 1}",
        )

    def _plan(self, raw_input: dict[str, Any], enabled: list[str]) -> list[dict[str, Any]]:
        text = user_text_from_input(raw_input)
        plan: list[dict[str, Any]] = []
        if "text_transform" in enabled:
            plan.append({"name": "text_transform", "arguments": {"operation": "trim", "text": text}})
            plan.append(
                {"name": "text_transform", "arguments": {"operation": "classify_urgency", "text": text}}
            )
        if "branch" in enabled and "text_transform" in enabled:
            plan.append(
                {
                    "name": "branch",
                    "arguments": {
                        "left": "",
                        "op": "eq",
                        "right": "high",
                        "then_value": "priority",
                        "else_value": "standard",
                    },
                }
            )
        url = raw_input.get("url")
        if "http_request" in enabled and isinstance(url, str) and url:
            plan.append({"name": "http_request", "arguments": {"method": "GET", "url": url}})
        if "store_record" in enabled:
            collection = raw_input.get("collection") if isinstance(raw_input.get("collection"), str) else "demo"
            plan.append(
                {
                    "name": "store_record",
                    "arguments": {"collection": collection, "data": {"text": text}},
                }
            )
        return plan

    def _record_data(self, raw_input: dict[str, Any], done: list[dict[str, Any]]) -> dict[str, Any]:
        urgency = None
        label = None
        for item in done:
            if item.get("operation") == "classify_urgency":
                urgency = item.get("result")
            if "branch" in item and "value" in item:
                label = item.get("value")
        return {
            "text": user_text_from_input(raw_input)[:1000],
            "urgency": urgency,
            "label": label,
        }

    def _summary(self, raw_input: dict[str, Any], done: list[dict[str, Any]]) -> str:
        text = user_text_from_input(raw_input)
        bits: list[str] = []
        for item in done:
            if item.get("operation"):
                bits.append(f"{item['operation']}={item.get('result')}")
            elif "value" in item and "branch" in item:
                bits.append(f"branch={item.get('value')}")
            elif item.get("record_id"):
                bits.append(f"stored={item['record_id']}")
            elif "status_code" in item:
                bits.append(f"http={item['status_code']}")
        detail = "; ".join(bits)
        summary = f"Processed message ({len(text)} characters)."
        if detail:
            summary = f"{summary} {detail}"
        return summary


class OpenAICompatibleLLM:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[str],
        attempt: int,
        raw_input: dict[str, Any],
        model: str,
    ) -> LLMDecision:
        del attempt, raw_input
        settings = get_settings()
        if not settings.llm_api_key:
            raise PermanentError("LLM API key is not configured")
        payload = {
            "model": model or settings.llm_model,
            "temperature": 0,
            "messages": messages,
            "tools": [TOOL_SCHEMAS[name] for name in tools if name in TOOL_SCHEMAS],
            "tool_choice": "auto",
        }
        owns_client = self._client is None
        http = self._client or httpx.Client(timeout=settings.llm_timeout_seconds)
        try:
            response = http.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise TransientLLMError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            raise TransientLLMError("LLM request failed") from exc
        finally:
            if owns_client:
                http.close()
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientLLMError(f"LLM provider returned {response.status_code}")
        if response.status_code >= 400:
            raise PermanentError(f"LLM provider rejected the request ({response.status_code})")
        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PermanentError("LLM provider returned an unreadable response") from exc
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            function = call.get("function") or {}
            name = function.get("name")
            if name not in ALLOWED_TOOLS:
                raise PermanentError("LLM selected a tool that is not allowlisted")
            raw_args = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError as exc:
                raise PermanentError("LLM returned invalid tool arguments") from exc
            if not isinstance(arguments, dict):
                raise PermanentError("Tool arguments must be an object")
            return LLMDecision(tool_name=name, arguments=arguments, tool_call_id=str(call.get("id") or "call_1"))
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content)
        return LLMDecision(content=content[:8000])


def get_llm(provider: str | None) -> MockLLM | OpenAICompatibleLLM:
    selected = provider or get_settings().llm_provider
    if selected == "mock":
        return MockLLM()
    if selected == "openai":
        return OpenAICompatibleLLM()
    raise PermanentError(f"Unknown LLM provider: {selected}")
