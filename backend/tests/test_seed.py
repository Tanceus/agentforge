from app.config import get_settings
from app.models import Task
from app.seed import seed
from sqlalchemy import func, select


def test_seed_is_idempotent(db):
    settings = get_settings()
    settings.seed_demo = True
    seed()
    seed()
    completed = db.scalar(select(func.count()).select_from(Task).where(Task.status == "completed"))
    assert completed == 1
