import time

from redis.exceptions import RedisError

from app.config import get_settings
from app.constants import rate_key
from app.errors import AppError
from app.redis_client import get_redis


def enforce_rate_limit(identity: str, scope: str, limit: int) -> None:
    if limit <= 0:
        return
    window = int(time.time()) // 60
    key = rate_key(scope, identity, window)
    try:
        client = get_redis()
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, 70)
    except RedisError as exc:
        raise AppError("dependency_unavailable", "Rate limiter is unavailable", 503) from exc
    if count > limit:
        raise AppError(
            "rate_limited",
            "Too many requests",
            429,
            details={"retry_after_seconds": 60},
        )


def client_ip(request) -> str:  # type: ignore[no-untyped-def]
    settings = get_settings()
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
