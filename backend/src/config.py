from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "TicketBookingCore"
    DEBUG: bool = False
    
    # Database Settings
    # Format: postgresql+psycopg2://user:password@localhost:5432/dbname
    DATABASE_URL: str
    
    # Security
    SECRET_KEY: str
    OTP_EXPIRY_MINUTES: int = 5
    
    # Logic Constraints
    SEAT_LOCK_DURATION_MINUTES: int = 10

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
