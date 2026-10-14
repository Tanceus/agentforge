from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, get_owned_agent
from app.errors import AppError
from app.models import Agent, User
from app.schemas.agent import AgentCreate, AgentOut, AgentUpdate
from app.schemas.common import Page
from app.security.rate_limit import enforce_rate_limit
from app.services.activity import record_activity
from app.timeutils import utcnow

router = APIRouter(prefix="/agents", tags=["agents"])


def _limit(user: User) -> None:
    enforce_rate_limit(user.id, "api", get_settings().rate_limit_per_minute)


@router.get("", response_model=Page[AgentOut])
def list_agents(
    q: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[AgentOut]:
    _limit(user)
    filters = [Agent.owner_id == user.id, Agent.status != "archived"]
    if status:
        if status not in {"draft", "active", "paused"}:
            raise AppError("validation_error", "Unknown agent status", 422)
        filters.append(Agent.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        filters.append(or_(func.lower(Agent.name).like(like), func.lower(Agent.description).like(like)))
    total = db.scalar(select(func.count()).select_from(Agent).where(*filters)) or 0
    rows = db.scalars(
        select(Agent).where(*filters).order_by(Agent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(items=[AgentOut.model_validate(row) for row in rows], total=total, page=page, page_size=page_size)


@router.post("", response_model=AgentOut, status_code=201)
def create_agent(payload: AgentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Agent:
    _limit(user)
    agent = Agent(
        owner_id=user.id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        system_prompt=payload.system_prompt.strip(),
        provider=payload.provider,
        model=payload.model,
        tools=payload.tools,
        status="draft",
        max_retries=payload.max_retries,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    record_activity(db, user.id, "agent.created", f"Created agent {agent.name}", agent_id=agent.id)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Agent:
    _limit(user)
    return get_owned_agent(db, user, agent_id)


@router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Agent:
    _limit(user)
    agent = get_owned_agent(db, user, agent_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(agent, field, value)
    agent.updated_at = utcnow()
    db.commit()
    db.refresh(agent)
    record_activity(db, user.id, "agent.updated", f"Updated agent {agent.name}", agent_id=agent.id)
    return agent


@router.post("/{agent_id}/start", response_model=AgentOut)
def start_agent(agent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Agent:
    _limit(user)
    agent = get_owned_agent(db, user, agent_id)
    if agent.status == "active":
        return agent
    if agent.status not in {"draft", "paused"}:
        raise AppError("invalid_state", "Agent cannot be started", 409)
    agent.status = "active"
    agent.updated_at = utcnow()
    db.commit()
    db.refresh(agent)
    record_activity(db, user.id, "agent.started", f"Started agent {agent.name}", agent_id=agent.id)
    return agent


@router.post("/{agent_id}/pause", response_model=AgentOut)
def pause_agent(agent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Agent:
    _limit(user)
    agent = get_owned_agent(db, user, agent_id)
    if agent.status != "active":
        raise AppError("invalid_state", "Only an active agent can be paused", 409)
    agent.status = "paused"
    agent.updated_at = utcnow()
    db.commit()
    db.refresh(agent)
    record_activity(db, user.id, "agent.paused", f"Paused agent {agent.name}", agent_id=agent.id)
    return agent


@router.delete("/{agent_id}", status_code=204)
def archive_agent(agent_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    _limit(user)
    agent = get_owned_agent(db, user, agent_id)
    agent.status = "archived"
    agent.updated_at = utcnow()
    db.commit()
    record_activity(db, user.id, "agent.archived", f"Archived agent {agent.name}", agent_id=agent.id)
    return Response(status_code=204)
