import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["JWT_SECRET"] = "test-secret-key-for-agentforge"
os.environ["SEED_DEMO"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["TASK_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["RETRY_BASE_SECONDS"] = "0"
os.environ["RETRY_MAX_SECONDS"] = "0"
os.environ["DASHBOARD_CACHE_SECONDS"] = "0"
os.environ["TRUST_PROXY"] = "false"

import pytest
import fakeredis
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, SessionLocal, get_engine, reset_db_state
from app.redis_client import reset_redis, set_redis


@pytest.fixture(autouse=True)
def _isolate_settings():
    get_settings.cache_clear()
    reset_db_state()
    reset_redis()
    yield
    get_settings.cache_clear()
    reset_db_state()
    reset_redis()


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    set_redis(client)
    yield client


@pytest.fixture
def db(redis_client):
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, email: str = "ada@example.com", password: str = "password123", name: str = "Ada Lovelace") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_agent(client: TestClient, token: str, **overrides) -> dict:
    payload = {
        "name": "Triage",
        "description": "Classify and store support messages",
        "system_prompt": "Triage the customer message and store the result.",
        "tools": ["text_transform", "branch", "store_record"],
        "max_retries": 2,
        "timeout_seconds": 30,
    }
    payload.update(overrides)
    created = client.post("/api/v1/agents", json=payload, headers=auth_header(token))
    assert created.status_code == 201, created.text
    started = client.post(f"/api/v1/agents/{created.json()['id']}/start", headers=auth_header(token))
    assert started.status_code == 200, started.text
    return started.json()
