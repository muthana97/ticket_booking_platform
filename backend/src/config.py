import os
from pydantic_settings import BaseSettings, SettingsConfigDict

current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, "..", ".env")

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "TicketBookingPlatform"
    DEBUG: bool = False
    
    # Database Settings
    DATABASE_URL: str
    
    # Security & JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    OTP_EXPIRY_MINUTES: int = 5
    
    # Logic Constraints
    SEAT_LOCK_DURATION_MINUTES: int = 10 # Requirement SEAT-04

    model_config = SettingsConfigDict(env_file=env_path)

settings = Settings()
