import httpx
import pytest

from app.integrations.tools import safe_fetch
from app.security.ssrf import SSRFError, validate_url
from app.workers.runner import process_available
from tests.conftest import auth_header, create_agent, register


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/secret",
        "http://127.0.0.1:80/",
        "http://localhost/admin",
        "http://10.1.2.3/internal",
        "http://192.168.1.20/router",
        "http://172.16.4.4/db",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://2130706433/",
        "file:///etc/passwd",
        "http://user:pass@8.8.8.8/",
        "http://instance-data.ec2.internal/",
    ],
)
def test_validate_url_rejects_blocked_targets(url):
    with pytest.raises(SSRFError):
        validate_url(url)


def test_validate_url_allows_public_literal():
    assert validate_url("http://8.8.8.8/health") == "8.8.8.8"


def test_redirect_to_loopback_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="should-not-be-read")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SSRFError):
        safe_fetch("GET", "http://8.8.8.8/start", client=client)


def test_http_tool_blocks_metadata_address_during_execution(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token, tools=["http_request"], max_retries=3)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={
            "input": {"text": "fetch metadata", "url": "http://169.254.169.254/latest/meta-data"},
            "idempotency_key": "ssrf-meta-0001",
        },
        headers=auth_header(token),
    )
    process_available()
    detail = client.get(f"/api/v1/tasks/{created.json()['id']}", headers=auth_header(token)).json()
    assert detail["status"] == "failed"
    assert detail["dead_letter"] is True
    assert detail["attempt"] == 0
    assert "not allowed" in (detail["error"] or "").lower() or "address" in (detail["error"] or "").lower()
