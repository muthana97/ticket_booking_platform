from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

UserRole = Literal["customer", "provider", "admin"]
UserStatus = Literal["pending", "active", "blocked"]


# ---------------------------------------------------------------------------
# Registration / verification / login
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    # Admin role cannot be self-registered — that route is blocked server-side.
    role: Literal["customer", "provider"] = "customer"


class RegisterResponse(BaseModel):
    message: str
    email: EmailStr
    role: UserRole
    status: UserStatus
    dev_otp: str  # demo-mode — strip in production


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    phone_number: Optional[str] = None
    role: UserRole
    status: UserStatus
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ResendOtpRequest(BaseModel):
    email: EmailStr
