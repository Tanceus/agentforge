from fastapi import APIRouter

from app.api import agents, auth, dashboard, health, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(agents.router, prefix="/api/v1")
api_router.include_router(tasks.router, prefix="/api/v1")
api_router.include_router(dashboard.router, prefix="/api/v1")
