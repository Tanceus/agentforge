from datetime import timedelta

from app.models import Task
from app.services.orchestrator import recover_expired_leases as recover
from app.timeutils import utcnow
from app.workers.runner import process_available
from tests.conftest import auth_header, create_agent, register


def test_transient_failure_retries_then_completes(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token, max_retries=2)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={
            "input": {"text": "Urgent: retry me", "simulate_transient_failures": 1},
            "idempotency_key": "retry-success-1",
        },
        headers=auth_header(token),
    )
    assert created.json()["status"] == "queued"
    process_available()
    detail = client.get(f"/api/v1/tasks/{created.json()['id']}", headers=auth_header(token))
    body = detail.json()
    assert body["status"] == "completed"
    assert body["attempt"] == 1
    assert body["dead_letter"] is False


def test_exhausted_retries_are_dead_lettered(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token, max_retries=1)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={
            "input": {"text": "Urgent: keep failing", "simulate_transient_failures": 5},
            "idempotency_key": "retry-dead-0001",
        },
        headers=auth_header(token),
    )
    process_available()
    detail = client.get(f"/api/v1/tasks/{created.json()['id']}", headers=auth_header(token)).json()
    assert detail["status"] == "failed"
    assert detail["dead_letter"] is True
    letters = client.get("/api/v1/dead-letters", headers=auth_header(token))
    assert letters.json()["total"] == 1
    retried = client.post(f"/api/v1/tasks/{detail['id']}/retry", headers=auth_header(token))
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["dead_letter"] is False


def test_expired_worker_lease_is_recovered(client, db):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "Urgent: crashed worker"}, "idempotency_key": "lease-recover-1"},
        headers=auth_header(token),
    )
    task = db.get(Task, created.json()["id"])
    task.status = "running"
    task.worker_id = "dead-worker"
    task.lease_expires_at = utcnow() - timedelta(minutes=5)
    task.started_at = utcnow() - timedelta(minutes=5)
    db.commit()
    assert recover() == 1
    process_available()
    detail = client.get(f"/api/v1/tasks/{task.id}", headers=auth_header(token)).json()
    assert detail["status"] == "completed"
