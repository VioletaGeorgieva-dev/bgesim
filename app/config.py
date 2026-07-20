from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # eSIM Access API
    esim_access_code: str
    esim_secret_key: str
    esim_base_url: str = "https://api.esimaccess.com"
    rate_limit_per_second: int = 8
    SUPPORT_EMAIL: str = ""
    SUPPORT_PHONE: str = ""
    ADMIN_PASSWORD: str = "admin123"
    ADMIN_USER: str = "admin"
    ALLOWED_ORIGINS: str = "https://твоя-домейн.com"

    # Email (Brevo HTTP API)
    smtp_sender_email: str = "info@bgesim.bg"
    smtp_sender_password: str = ""  # запазен за backward compat
    brevo_api_key: str = ""

    # Stripe
    stripe_publishable_key: str
    stripe_secret_key: str
    stripe_webhook_secret: str
    partner_session_secret: str = ""

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"  # ← игнорира непознати полета в .env


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
