from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes_health import router as health_router
from app.api.routes_documents import router as documents_router
from app.api.routes_ai import router as ai_router
from app.api.routes_compile import router as compile_router
from app.api.routes_auth import router as auth_router
from app.middleware.utf8 import UTF8Middleware

app = FastAPI(title=settings.APP_NAME)

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(UTF8Middleware)

app.include_router(health_router, tags=["Health"])
app.include_router(documents_router)
app.include_router(ai_router)
app.include_router(compile_router)
app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": f"Welcome to {settings.APP_NAME}!"}