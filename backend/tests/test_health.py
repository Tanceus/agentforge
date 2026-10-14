def test_health_ready_and_metrics(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok"
    assert ready.json()["checks"]["redis"] == "ok"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "agentforge_http_requests_total" in metrics.text
    assert client.get("/").json()["service"] == "agentforge"


def test_validation_errors(client):
    short = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short", "full_name": ""},
    )
    assert short.status_code == 422
    assert short.json()["error"]["code"] == "validation_error"

    created = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "password": "password123", "full_name": "Ada"},
    )
    token = created.json()["access_token"]
    bad_tool = client.post(
        "/api/v1/agents",
        json={
            "name": "Unsafe",
            "description": "",
            "system_prompt": "Do work",
            "tools": ["shell"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad_tool.status_code == 422
    empty = client.post(
        "/api/v1/agents",
        json={
            "name": "Empty input later",
            "description": "",
            "system_prompt": "Do work",
            "tools": ["text_transform"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    agent_id = empty.json()["id"]
    client.post(f"/api/v1/agents/{agent_id}/start", headers={"Authorization": f"Bearer {token}"})
    missing_input = client.post(
        f"/api/v1/agents/{agent_id}/tasks",
        json={"input": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing_input.status_code == 422
    unauthenticated = client.get("/api/v1/agents")
    assert unauthenticated.status_code == 401
