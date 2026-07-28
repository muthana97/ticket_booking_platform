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
    national_id: Optional[str] = Field(default=None, max_length=40)
    # Admin role cannot be self-registered — that route is blocked server-side.
    role: Literal["customer", "provider"] = "customer"


class RegisterResponse(BaseModel):
    message: str
    email: EmailStr
    role: UserRole
    status: UserStatus
    dev_otp: Optional[str] = None  # only populated when settings.DEBUG is true


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
    national_id: Optional[str] = None
    role: UserRole
    status: UserStatus
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    """Partial update payload for PATCH /auth/me.

    Every field is optional in the wire format:
      - absent    → don't touch the column
      - null      → set the column to NULL (phone_number, national_id only)
      - string    → set the column to that value

    `full_name` cannot be cleared: sending null is treated as "absent" by
    the service layer since the ORM column is NOT NULL. min_length matches
    RegisterRequest so any name that was valid at signup stays valid on edit.
    """
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    national_id: Optional[str] = Field(default=None, max_length=40)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ResendOtpRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)
