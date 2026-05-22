import random
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from . import models, utils


def _generate_email_otp(db: Session, email: str) -> str:
    code = f"{random.randint(100000, 999999)}"
    rec = models.EmailOTP(
        email=email,
        otp_code=code,
        purpose="verify",
        expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    db.add(rec)
    db.commit()
    # In production this would hand off to an email transport. For the demo we
    # surface the code via the response (matching the existing dev pattern).
    print(f"[EMAIL-OTP] {email} → {code}")
    return code


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    role: str,
    phone_number: str | None = None,
) -> tuple[models.User, str]:
    """Register a new user.

    Customers are immediately `active` once they verify their email.
    Providers land in `pending` and need admin approval before they can
    create trips.

    Returns the new user and the dev-mode OTP (for the response payload).
    """
    if role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin accounts cannot be self-registered.",
        )

    existing = db.query(models.User).filter(models.User.email == email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    new_status = "pending" if role == "provider" else "active"
    user = models.User(
        email=email.lower(),
        password_hash=utils.hash_password(password),
        full_name=full_name.strip(),
        phone_number=phone_number,
        role=role,
        status=new_status,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    otp = _generate_email_otp(db, user.email)
    return user, otp


def verify_email(db: Session, *, email: str, otp_code: str) -> models.User:
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rec = (
        db.query(models.EmailOTP)
        .filter(
            models.EmailOTP.email == email.lower(),
            models.EmailOTP.otp_code == otp_code,
            models.EmailOTP.purpose == "verify",
        )
        .order_by(models.EmailOTP.id.desc())
        .first()
    )
    if not rec or rec.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    user.email_verified = True
    db.delete(rec)
    db.commit()
    db.refresh(user)
    return user


def resend_email_otp(db: Session, *, email: str) -> str:
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        raise HTTPException(status_code=400, detail="Email is already verified")
    return _generate_email_otp(db, user.email)


def authenticate(db: Session, *, email: str, password: str) -> models.User:
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user or not utils.verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Verify your email before signing in. Check the registration OTP.",
        )
    if user.status == "blocked":
        raise HTTPException(status_code=403, detail="Account blocked. Contact an administrator.")
    return user
