import logging

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Agent, Task, User
from app.security.passwords import hash_password
from app.services.activity import record_activity

logger = logging.getLogger(__name__)

DEMO_AGENT_NAME = "Support Triage"
DEMO_IDEMPOTENCY_KEY = "seed-demo-urgent-login"
DEMO_INPUT = {"text": "Urgent: customer cannot log in to the billing portal"}


def _ensure_user(db, email: str, password: str, full_name: str, role: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user:
        return user
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed() -> None:
    settings = get_settings()
    if not settings.seed_demo:
        return
    if settings.environment == "production":
        logger.warning("skipping demo seed because ENVIRONMENT=production")
        return
    db = SessionLocal()
    try:
        demo = _ensure_user(
            db,
            settings.demo_user_email,
            settings.demo_user_password,
            "Demo Operator",
            "user",
        )
        _ensure_user(
            db,
            settings.admin_user_email,
            settings.admin_user_password,
            "Platform Admin",
            "admin",
        )
        agent = db.scalar(select(Agent).where(Agent.owner_id == demo.id, Agent.name == DEMO_AGENT_NAME))
        if agent is None:
            agent = Agent(
                owner_id=demo.id,
                name=DEMO_AGENT_NAME,
                description="Classifies a support message, branches on urgency, and stores the triage record.",
                system_prompt=(
                    "You triage customer support messages. Classify urgency, branch priority versus standard, "
                    "and store the resulting record. Do not invent tools."
                ),
                provider="mock",
                model="mock-triage-v1",
                tools=["text_transform", "branch", "store_record"],
                status="active",
                max_retries=2,
                timeout_seconds=60,
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            record_activity(db, demo.id, "agent.created", "Seeded the Support Triage demo agent", agent_id=agent.id)

        existing = db.scalar(
            select(Task).where(Task.owner_id == demo.id, Task.idempotency_key == DEMO_IDEMPOTENCY_KEY)
        )
        if existing is None:
            from app.services.orchestrator import create_task
            from app.workers.runner import process_available

            create_task(
                db,
                agent,
                demo.id,
                DEMO_INPUT,
                DEMO_IDEMPOTENCY_KEY,
                "Urgent billing login",
            )
            process_available()
            logger.info("seeded demo user, agent, and completed execution")
        else:
            logger.info("demo data already present")
    finally:
        db.close()


if __name__ == "__main__":
    from app.logging_config import configure_logging

    configure_logging(get_settings().log_level)
    seed()
