from app.workers.runner import process_available
from tests.conftest import auth_header, create_agent, register


def _run(client, token, agent_id, payload, key):
    response = client.post(
        f"/api/v1/agents/{agent_id}/tasks",
        json={"input": payload, "idempotency_key": key, "title": "Demo run"},
        headers=auth_header(token),
    )
    assert response.status_code == 201, response.text
    process_available()
    detail = client.get(f"/api/v1/tasks/{response.json()['id']}", headers=auth_header(token))
    assert detail.status_code == 200
    return detail.json()


def test_demo_workflow_persists_history(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    detail = _run(
        client,
        token,
        agent["id"],
        {"text": "Urgent: customer cannot log in to the billing portal"},
        "demo-urgent-001",
    )
    assert detail["status"] == "completed"
    assert detail["dead_letter"] is False
    assert "Processed message" in detail["result"]["summary"]
    names = [step["name"] for step in detail["steps"]]
    assert "text_transform" in names
    assert "branch" in names
    assert "store_record" in names
    urgency = next(step["output"]["result"] for step in detail["steps"] if step["output"] and step["output"].get("operation") == "classify_urgency")
    assert urgency == "high"
    branch = next(step["output"]["value"] for step in detail["steps"] if step["name"] == "branch")
    assert branch == "priority"

    records = client.get("/api/v1/records", params={"task_id": detail["id"]}, headers=auth_header(token))
    assert records.json()["total"] == 1
    assert records.json()["items"][0]["data"]["label"] == "priority"

    dashboard = client.get("/api/v1/dashboard", headers=auth_header(token))
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["tasks_by_status"]["completed"] == 1
    assert body["system"]["database"] == "ok"
    assert body["system"]["redis"] == "ok"
    assert body["recent_activity"]


def test_standard_message_branches_to_standard(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    detail = _run(client, token, agent["id"], {"text": "Thanks, the invoice looks fine"}, "demo-normal-001")
    branch = next(step["output"]["value"] for step in detail["steps"] if step["name"] == "branch")
    assert branch == "standard"


def test_cancel_before_execution(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "Please hold this"}, "idempotency_key": "cancel-me-001"},
        headers=auth_header(token),
    )
    cancelled = client.post(f"/api/v1/tasks/{created.json()['id']}/cancel", headers=auth_header(token))
    assert cancelled.json()["status"] == "cancelled"
    process_available()
    detail = client.get(f"/api/v1/tasks/{created.json()['id']}", headers=auth_header(token))
    assert detail.json()["status"] == "cancelled"
    records = client.get("/api/v1/records", headers=auth_header(token))
    assert records.json()["total"] == 0


def test_sse_returns_terminal_snapshot(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    detail = _run(client, token, agent["id"], {"text": "Urgent: portal outage"}, "sse-demo-0001")
    with client.stream("GET", f"/api/v1/tasks/{detail['id']}/events", headers=auth_header(token)) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "event: task" in body
    assert "completed" in body


def test_task_search_and_pagination(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    _run(client, token, agent["id"], {"text": "Urgent: billing portal"}, "page-urgent-01")
    _run(client, token, agent["id"], {"text": "Thanks, all good"}, "page-thanks-01")
    found = client.get("/api/v1/tasks", params={"q": "billing", "page_size": 1}, headers=auth_header(token))
    assert found.status_code == 200
    assert found.json()["total"] == 1
    assert found.json()["page_size"] == 1
