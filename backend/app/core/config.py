from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "latex-ai-backend"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Required
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SECRET_KEY: str = "local-development-secret-key"
    GROQ_API_KEY: str
    OPENROUTER_API_KEY: str = ""

    # Optional (with defaults)
    GEMINI_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    BACKEND_CORS_ORIGINS: list = ["http://localhost:5173"]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
