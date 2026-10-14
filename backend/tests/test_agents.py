from tests.conftest import auth_header, create_agent, register


def test_agent_lifecycle_and_filters(client):
    token = register(client)["access_token"]
    headers = auth_header(token)
    created = client.post(
        "/api/v1/agents",
        json={
            "name": "Inbox Agent",
            "description": "Sorts inbound notes",
            "system_prompt": "Summarize the note.",
            "tools": ["text_transform", "store_record"],
            "max_retries": 1,
            "timeout_seconds": 20,
        },
        headers=headers,
    )
    assert created.status_code == 201
    agent = created.json()
    assert agent["status"] == "draft"
    started = client.post(f"/api/v1/agents/{agent['id']}/start", headers=headers)
    assert started.json()["status"] == "active"
    paused = client.post(f"/api/v1/agents/{agent['id']}/pause", headers=headers)
    assert paused.json()["status"] == "paused"
    edited = client.patch(
        f"/api/v1/agents/{agent['id']}",
        json={"description": "Updated description"},
        headers=headers,
    )
    assert edited.status_code == 200
    listed = client.get("/api/v1/agents", params={"q": "updated", "status": "paused"}, headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    archived = client.delete(f"/api/v1/agents/{agent['id']}", headers=headers)
    assert archived.status_code == 204
    missing = client.get(f"/api/v1/agents/{agent['id']}", headers=headers)
    assert missing.status_code == 404


def test_paused_agent_rejects_tasks(client):
    token = register(client)["access_token"]
    agent = create_agent(client, token)
    paused = client.post(f"/api/v1/agents/{agent['id']}/pause", headers=auth_header(token))
    assert paused.status_code == 200
    rejected = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "hello"}},
        headers=auth_header(token),
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "agent_not_active"
