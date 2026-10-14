"""Exercise a running AgentForge API. Exits exit code is non-zero on failure."""

import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTFORGE_BASE_URL", "http://localhost:8000")


def request(method: str, path: str, body: dict | None = None, token: str | None = None, headers: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req_headers = {"content-type": "application/json"}
    if token:
        req_headers["authorization"] = f"Bearer {token}"
    if headers:
        req_headers.update(headers)
    request_obj = urllib.request.Request(BASE + path, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=20) as response:
            raw = response.read().decode()
            parsed = json.loads(raw) if raw else None
            return response.status, dict(response.headers), parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        parsed = json.loads(raw) if raw else None
        return exc.code, dict(exc.headers), parsed


def wait_ready() -> None:
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            status, _, payload = request("GET", "/ready")
            if status == 200 and payload and payload.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("API did not become ready")


def main() -> None:
    wait_ready()
    email = f"verify-{int(time.time())}@example.com"
    status, _, registered = request(
        "POST",
        "/api/v1/auth/register",
        {"email": email, "password": "password123", "full_name": "Verify User"},
    )
    assert status == 201, registered
    token = registered["access_token"]

    status, _, logged = request("POST", "/api/v1/auth/login", {"email": email, "password": "password123"})
    assert status == 200, logged

    status, _, agent = request(
        "POST",
        "/api/v1/agents",
        {
            "name": "Verify Triage",
            "description": "HTTP verification agent",
            "system_prompt": "Classify, branch, and store the message.",
            "tools": ["text_transform", "branch", "store_record"],
            "max_retries": 1,
            "timeout_seconds": 30,
        },
        token,
    )
    assert status == 201, agent
    status, _, started = request("POST", f"/api/v1/agents/{agent['id']}/start", token=token)
    assert status == 200 and started["status"] == "active"

    status, headers, task = request(
        "POST",
        f"/api/v1/agents/{agent['id']}/tasks",
        {"input": {"text": "Urgent: customer cannot log in to the billing portal"}, "idempotency_key": "verify-demo-0001"},
        token,
    )
    assert status == 201, task
    status, replay_headers, replay = request(
        "POST",
        f"/api/v1/agents/{agent['id']}/tasks",
        {"input": {"text": "Urgent: customer cannot log in to the billing portal"}, "idempotency_key": "verify-demo-0001"},
        token,
    )
    assert status == 200 and replay["id"] == task["id"], replay
    assert replay_headers.get("Idempotency-Replayed") == "true" or replay_headers.get("idempotency-replayed") == "true"

    detail = None
    deadline = time.time() + 40
    while time.time() < deadline:
        _, _, detail = request("GET", f"/api/v1/tasks/{task['id']}", token=token)
        if detail and detail["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(1)
    assert detail and detail["status"] == "completed", detail
    assert any(step["name"] == "store_record" for step in detail["steps"])
    _, _, records = request("GET", f"/api/v1/records?task_id={task['id']}", token=token)
    assert records["total"] == 1
    events = urllib.request.Request(
        BASE + f"/api/v1/tasks/{task['id']}/events",
        headers={"authorization": f"Bearer {token}", "accept": "text/event-stream"},
    )
    with urllib.request.urlopen(events, timeout=20) as stream:
        event_body = stream.read().decode()
    assert "event: task" in event_body and "completed" in event_body

    status, _, other = request(
        "POST",
        "/api/v1/auth/register",
        {"email": f"other-{int(time.time())}@example.com", "password": "password123", "full_name": "Other User"},
    )
    assert status == 201
    hidden = request("GET", f"/api/v1/agents/{agent['id']}", token=other["access_token"])
    assert hidden[0] == 404

    status, _, ssrf_agent = request(
        "POST",
        "/api/v1/agents",
        {
            "name": "SSRF check",
            "system_prompt": "Fetch the URL.",
            "tools": ["http_request"],
            "max_retries": 0,
            "timeout_seconds": 20,
        },
        token,
    )
    assert status == 201
    request("POST", f"/api/v1/agents/{ssrf_agent['id']}/start", token=token)
    _, _, ssrf_task = request(
        "POST",
        f"/api/v1/agents/{ssrf_agent['id']}/tasks",
        {"input": {"text": "metadata", "url": "http://169.254.169.254/latest/meta-data"}, "idempotency_key": "verify-ssrf-0001"},
        token,
    )
    deadline = time.time() + 30
    ssrf_detail = None
    while time.time() < deadline:
        _, _, ssrf_detail = request("GET", f"/api/v1/tasks/{ssrf_task['id']}", token=token)
        if ssrf_detail and ssrf_detail["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(1)
    assert ssrf_detail and ssrf_detail["status"] == "failed" and ssrf_detail["dead_letter"] is True, ssrf_detail

    status, _, demo = request(
        "POST",
        "/api/v1/auth/login",
        {"email": "demo@example.com", "password": "DemoPass123!"},
    )
    assert status == 200, demo
    _, _, dashboard = request("GET", "/api/v1/dashboard", token=demo["access_token"])
    assert dashboard["tasks_by_status"]["completed"] >= 1
    assert dashboard["system"]["database"] == "ok"
    assert dashboard["system"]["redis"] == "ok"
    print(json.dumps({"ok": True, "task_id": task["id"], "summary": detail["result"]["summary"]}, indent=2))


if __name__ == "__main__":
    main()
