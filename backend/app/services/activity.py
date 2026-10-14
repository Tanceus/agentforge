from sqlalchemy.orm import Session

from app.models import Activity
from app.timeutils import utcnow


def record_activity(
    db: Session,
    owner_id: str,
    event_type: str,
    message: str,
    agent_id: str | None = None,
    task_id: str | None = None,
    details: dict | None = None,
) -> Activity:
    row = Activity(
        owner_id=owner_id,
        agent_id=agent_id,
        task_id=task_id,
        event_type=event_type,
        message=message[:500],
        details=details or {},
        created_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
