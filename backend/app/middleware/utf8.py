from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class UTF8Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        return response