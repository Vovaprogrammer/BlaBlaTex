"""Регистрация, вход и выход. Пока заглушки: логику добавит B1.2."""

from fastapi import APIRouter

from app.core.errors import not_implemented
from app.modules.auth.schemas import LoginRequest, MeResponse, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(body: RegisterRequest) -> MeResponse:
    """Создаёт пользователя с пустым профилем и сразу входит: ставит cookie bbt_session."""
    raise not_implemented()


@router.post("/login")
async def login(body: LoginRequest) -> MeResponse:
    """Вход по email и паролю: ставит cookie bbt_session."""
    raise not_implemented()


@router.post("/logout", status_code=204)
async def logout() -> None:
    """Завершает текущую сессию и удаляет cookie."""
    raise not_implemented()


@router.get("/me")
async def me() -> MeResponse:
    """Текущий пользователь и его профиль."""
    raise not_implemented()
