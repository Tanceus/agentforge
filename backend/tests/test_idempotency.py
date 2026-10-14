from app.constants import QUEUE_KEY
from app.redis_client import get_redis
from app.workers.runner import process_available
from tests.conftest import auth_header, create_agent, register


def test_same_idempotency_key_returns_one_task(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    headers = auth_header(token)
    payload = {"input": {"text": "Urgent: duplicate check"}, "idempotency_key": "same-key-0001"}
    first = client.post(f"/api/v1/agents/{agent['id']}/tasks", json=payload, headers=headers)
    second = client.post(f"/api/v1/agents/{agent['id']}/tasks", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["idempotency-replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]
    process_available()
    records = client.get("/api/v1/records", headers=headers)
    assert records.json()["total"] == 1
    tasks = client.get("/api/v1/tasks", headers=headers)
    assert tasks.json()["total"] == 1


def test_duplicate_queue_entries_execute_once(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "Urgent: only once"}, "idempotency_key": "queue-once-01"},
        headers=auth_header(token),
    )
    task_id = created.json()["id"]
    get_redis().rpush(QUEUE_KEY, task_id)
    process_available()
    records = client.get("/api/v1/records", headers=auth_header(token))
    assert records.json()["total"] == 1
    detail = client.get(f"/api/v1/tasks/{task_id}", headers=auth_header(token))
    assert detail.json()["status"] == "completed"


def test_header_idempotency_key(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    headers = auth_header(token)
    headers["Idempotency-Key"] = "header-key-01"
    first = client.post(f"/api/v1/agents/{agent['id']}/tasks", json={"input": {"text": "Hello queue"}}, headers=headers)
    second = client.post(f"/api/v1/agents/{agent['id']}/tasks", json={"input": {"text": "Hello queue"}}, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
