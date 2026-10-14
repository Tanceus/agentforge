"""Shared constants for task lifecycle and the tool allowlist."""

TASK_STATUSES = ("pending", "queued", "running", "completed", "failed", "cancelled")
TERMINAL_TASK_STATUSES = ("completed", "failed", "cancelled")
AGENT_STATUSES = ("draft", "active", "paused", "archived")
ALLOWED_TOOLS = ("http_request", "text_transform", "branch", "store_record")
USER_ROLES = ("user", "admin")

QUEUE_KEY = "agentforge:queue"
DELAYED_KEY = "agentforge:delayed"


def queue_marker(task_id: str) -> str:
    return f"agentforge:queued:{task_id}"


def event_channel(task_id: str) -> str:
    return f"agentforge:events:{task_id}"


def dashboard_cache_key(user_id: str) -> str:
    return f"agentforge:cache:dashboard:{user_id}"


def refresh_key(jti: str) -> str:
    return f"agentforge:refresh:{jti}"


def rate_key(scope: str, identity: str, window: int) -> str:
    return f"agentforge:rl:{scope}:{identity}:{window}"


def worker_key(worker_id: str) -> str:
    return f"agentforge:worker:{worker_id}"
