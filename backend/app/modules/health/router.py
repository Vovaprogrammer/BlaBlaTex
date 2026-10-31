"""Проверка живости API."""

from fastapi import APIRouter

from app.modules.health.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
