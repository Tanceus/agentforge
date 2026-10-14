from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.database import ping_database
from app.redis_client import ping_redis
from app.services.orchestrator import refresh_queue_depth

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    checks = {"database": "ok", "redis": "ok"}
    try:
        ping_database()
    except Exception:
        checks["database"] = "unavailable"
    try:
        ping_redis()
        refresh_queue_depth()
    except Exception:
        checks["redis"] = "unavailable"
    ok = all(value == "ok" for value in checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "unavailable", "checks": checks})


@router.get("/metrics")
def metrics() -> Response:
    try:
        refresh_queue_depth()
    except Exception:
        pass
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
