import os
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, "..", ".env")

# Capacitor webview schemes — iOS uses capacitor://localhost, Android uses
# https://localhost (or http://localhost in dev). ionic://localhost covers
# older Ionic shells if the app is ever rebranded.
_CAPACITOR_ORIGINS = (
    "capacitor://localhost",
    "https://localhost",
    "http://localhost",
    "ionic://localhost",
)


class Settings(BaseSettings):
    # ----- App -----
    APP_NAME: str = "TicketBookingPlatform"
    DEBUG: bool = False

    # ----- Database -----
    DATABASE_URL: str
    DB_POOL_SIZE: int = 5
    DB_POOL_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800  # recycle connections every 30 min

    # ----- Security & JWT -----
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    OTP_EXPIRY_MINUTES: int = 5

    # ----- Logic constraints -----
    SEAT_LOCK_DURATION_MINUTES: int = 10  # SEAT-04

    # ----- CORS -----
    # Comma-separated list of allowed origins. Use "*" in dev / set explicit
    # origins in production (e.g. "https://tazkirati.onrender.com").
    # Capacitor webview schemes are always appended when a strict list is set,
    # so the iOS + Android wrappers can hit the API.
    CORS_ALLOWED_ORIGINS: str = "*"

    # ----- Resend (HTTP email API — https://resend.com/docs) -----
    # If unset (or the sender domain isn't verified in Resend), _send_email
    # returns False and OTPs fall back to the [EMAIL-OTP-CONSOLE] server log.
    # This keeps local dev workable without a live API key.
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: Optional[str] = None  # e.g. "Tazkirati <noreply@yourdomain.com>"

    model_config = SettingsConfigDict(env_file=env_path, extra="ignore")

    @property
    def cors_origins(self) -> List[str]:
        raw = self.CORS_ALLOWED_ORIGINS.strip()
        if raw == "*" or not raw:
            return ["*"]
        configured = [o.strip() for o in raw.split(",") if o.strip()]
        # Always allow Capacitor webview origins so native apps can reach the API
        # without the operator having to remember to list them.
        for scheme in _CAPACITOR_ORIGINS:
            if scheme not in configured:
                configured.append(scheme)
        return configured


settings = Settings()
