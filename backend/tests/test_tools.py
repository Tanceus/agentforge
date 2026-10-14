import json

import httpx

from app.integrations.llm import OpenAICompatibleLLM
from app.integrations.tools import TextTransformArgs, run_branch, run_text_transform
from app.integrations.tools import BranchArgs
from app.config import get_settings
from app.errors import PermanentError


def test_text_transform_and_branch():
    trimmed = run_text_transform(TextTransformArgs(operation="trim", text="  Hello  "))
    assert trimmed["result"] == "Hello"
    urgent = run_text_transform(TextTransformArgs(operation="classify_urgency", text="This is urgent"))
    assert urgent["result"] == "high"
    calm = run_text_transform(TextTransformArgs(operation="classify_urgency", text="Thanks, all set"))
    assert calm["result"] == "normal"
    decision = run_branch(
        BranchArgs(left="high", op="eq", right="high", then_value="priority", else_value="standard")
    )
    assert decision["value"] == "priority"


def test_openai_compatible_parser(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_api_key", "test-key")
    monkeypatch.setattr(get_settings(), "llm_base_url", "https://example.invalid/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "text_transform",
                                        "arguments": json.dumps({"operation": "trim", "text": "Hi"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    llm = OpenAICompatibleLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))
    decision = llm.complete([], ["text_transform"], attempt=1, raw_input={}, model="gpt-test")
    assert decision.tool_name == "text_transform"
    assert decision.arguments["operation"] == "trim"


def test_openai_provider_requires_a_key():
    llm = OpenAICompatibleLLM()
    try:
        llm.complete([], ["text_transform"], attempt=1, raw_input={}, model="gpt-test")
        raise AssertionError("expected a configuration error")
    except PermanentError as exc:
        assert "API key" in str(exc)
