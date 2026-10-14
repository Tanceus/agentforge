from app.config import get_settings
from tests.conftest import auth_header, create_agent, register


def test_task_creation_is_rate_limited(client, monkeypatch):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    monkeypatch.setattr(get_settings(), "task_rate_limit_per_minute", 2)
    headers = auth_header(token)
    statuses = []
    for index in range(3):
        response = client.post(
            f"/api/v1/agents/{agent['id']}/tasks",
            json={"input": {"text": f"message {index}"}, "idempotency_key": f"rate-limit-{index:02d}"},
            headers=headers,
        )
        statuses.append(response.status_code)
    assert statuses[:2] == [201, 201]
    assert statuses[2] == 429
    assert client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "again"}, "idempotency_key": "rate-limit-03"},
        headers=headers,
    ).headers["retry-after"] == "60"


def test_queue_outage_is_retryable(client, monkeypatch):
    from redis.exceptions import RedisError

    token = register(client)["access_token"]
    agent = create_agent(client, token)

    def explode(_task_id: str) -> None:
        raise RedisError("redis down")

    monkeypatch.setattr("app.services.orchestrator.enqueue_now", explode)
    failed = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "hold please"}, "idempotency_key": "outage-key-001"},
        headers=auth_header(token),
    )
    assert failed.status_code == 503
    monkeypatch.undo()
    replayed = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "hold please"}, "idempotency_key": "outage-key-001"},
        headers=auth_header(token),
    )
    assert replayed.status_code == 200
    assert replayed.json()["status"] == "queued"
