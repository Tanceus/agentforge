from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import get_settings
from app.database import reset_db_state


def test_alembic_upgrade_creates_schema(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    reset_db_state()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"users", "agents", "tasks", "task_steps", "activity", "stored_records", "dead_letters"} <= tables
    engine.dispose()
