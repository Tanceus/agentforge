from tests.conftest import auth_header, create_agent, register


def test_users_cannot_read_each_others_agents_or_tasks(client):
    ada = register(client, email="ada@example.com")["access_token"]
    grace = register(client, email="grace@example.com", name="Grace Hopper")["access_token"]
    agent = create_agent(client, ada)
    hidden = client.get(f"/api/v1/agents/{agent['id']}", headers=auth_header(grace))
    assert hidden.status_code == 404
    listed = client.get("/api/v1/agents", headers=auth_header(grace))
    assert listed.json()["total"] == 0
    stolen = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "nope"}},
        headers=auth_header(grace),
    )
    assert stolen.status_code == 404

    created = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        json={"input": {"text": "Ada only"}, "idempotency_key": "tenant-task-01"},
        headers=auth_header(ada),
    )
    task_id = created.json()["id"]
    assert client.get(f"/api/v1/tasks/{task_id}", headers=auth_header(grace)).status_code == 404
    assert client.get("/api/v1/tasks", headers=auth_header(grace)).json()["total"] == 0
    assert client.get("/api/v1/records", headers=auth_header(grace)).json()["total"] == 0
