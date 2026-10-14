import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.errors import AppError
from app.logging_config import configure_logging
from app.metrics import http_request_duration_seconds, http_requests_total

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.seed_demo and settings.environment != "test":
        try:
            from app.seed import seed

            seed()
        except Exception:
            logger.exception("demo seed failed")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AgentForge",
        version="1.0.0",
        summary="Distributed AI agent platform",
        description=(
            "Create tenant-scoped agents, queue tasks, and execute them with an allowlisted tool set. "
            "PostgreSQL stores durable execution history. Redis coordinates the queue, retries, and live events."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Idempotency-Replayed", "Retry-After"],
    )

    @app.middleware("http")
    async def guard_and_measure(request: Request, call_next):
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > get_settings().max_request_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "payload_too_large",
                                "message": "Request body is too large",
                                "details": None,
                            }
                        },
                    )
                    response.headers["X-Request-ID"] = request_id
                    return response
            except ValueError:
                pass
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled request error")
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "Internal server error", "details": None}},
            )
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        http_requests_total.labels(request.method, path, str(response.status_code)).inc()
        http_request_duration_seconds.labels(request.method, path).observe(time.perf_counter() - started)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": "60"} if exc.status_code == 429 else {}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(err.get("loc", [])), "msg": str(err.get("msg")), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": details,
                }
            },
        )

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {"service": "agentforge", "docs": "/docs"}

    app.include_router(api_router)
    return app


app = create_app()
