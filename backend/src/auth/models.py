from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Boolean

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    national_id = Column(String, nullable=True)

    # 'customer' | 'provider' | 'admin' — set at registration, persisted forever.
    role = Column(String, nullable=False, default="customer")
    # 'pending' | 'active' | 'blocked'
    # Customers go straight to 'active' after email verification.
    # Providers land 'pending' and require admin approval.
    # Admins are seeded as 'active'.
    status = Column(String, nullable=False, default="active")
    email_verified = Column(Boolean, default=False, nullable=False)

    # Per-provider capability toggles (ADMIN-2, 2026-07-13). Meaningful only
    # for role=='provider' rows. Admins flip these from the Providers tab to
    # restrict a specific operator without fully blocking them.
    can_add_trips    = Column(Boolean, default=True, nullable=False)
    can_edit_trips   = Column(Boolean, default=True, nullable=False)
    can_delete_trips = Column(Boolean, default=True, nullable=False)
    can_view_reports = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class EmailOTP(Base):
    __tablename__ = "email_otps"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    otp_code = Column(String, nullable=False)
    purpose = Column(String, nullable=False, default="verify")  # 'verify' for now
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
