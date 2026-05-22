import random
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from . import models, utils


def _send_email(to: str, subject: str, html: str, text: str) -> bool:
    """
    Deliver an email via SMTP if credentials are configured. Returns True on
    success. On failure (or no config) we silently fall back to a console log
    of the OTP — the demo still works locally that way.
    """
    if not (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD):
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
            s.starttls()
            # Gmail App Passwords are tolerant of spaces, but strip just in case.
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD.replace(" ", ""))
            s.send_message(msg)
        print(f"[EMAIL] sent to {to} subject={subject!r}")
        return True
    except Exception as e:
        print(f"[EMAIL] SMTP delivery failed: {e!r}")
        return False


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

    subject = f"Your Tazkirati verification code: {code}"
    text = (
        f"Welcome to Tazkirati.\n\n"
        f"Your 6-digit verification code is: {code}\n"
        f"It expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
        f"If you didn't request this, you can safely ignore it."
    )
    html = f"""\
<!doctype html>
<html><body style="font-family: -apple-system, system-ui, sans-serif; background: #F2EAD3; padding: 32px;">
  <table style="max-width: 480px; margin: 0 auto; background: #FBF6E7; border: 1.5px solid #2D261B;">
    <tr><td style="padding: 28px 32px 14px;">
      <div style="font-family: Georgia, serif; font-weight: 900; font-size: 32px; color: #1A1814; letter-spacing: -0.02em;">Tazkirati.</div>
      <div style="font-family: monospace; font-size: 10px; letter-spacing: 0.2em; color: #3D362A; text-transform: uppercase; margin-top: 4px;">Sudan Intercity Coach</div>
    </td></tr>
    <tr><td style="padding: 0 32px 28px;">
      <p style="font-size: 15px; color: #1A1814; margin: 18px 0;">Welcome aboard. Use this code to confirm your email:</p>
      <div style="font-family: monospace; font-weight: 600; font-size: 40px; letter-spacing: 0.4em; padding: 18px; background: #F2EAD3; border: 2px solid #0F2A47; color: #0F2A47; text-align: center;">{code}</div>
      <p style="font-size: 12px; color: #3D362A; margin-top: 16px;">Valid for {settings.OTP_EXPIRY_MINUTES} minutes. If you didn't request this, ignore it.</p>
    </td></tr>
  </table>
</body></html>"""

    sent = _send_email(to=email, subject=subject, html=html, text=text)
    if not sent:
        # Fallback when SMTP isn't configured (or fails) — keeps local dev working.
        print(f"[EMAIL-OTP-CONSOLE] {email} → {code}")
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

    new_status = "pending" if role == "provider" else "active"
    existing = db.query(models.User).filter(models.User.email == email.lower()).first()

    if existing and existing.email_verified:
        # Real, completed account — block the duplicate sign-up.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    if existing and not existing.email_verified:
        # Previous attempt that never verified — overwrite the record so the
        # caller can pick up where they left off (or change their details).
        existing.password_hash = utils.hash_password(password)
        existing.full_name = full_name.strip()
        existing.phone_number = phone_number
        existing.role = role
        existing.status = new_status
        # Drop any prior unverified OTPs for this email so only the new one
        # is valid going forward.
        db.query(models.EmailOTP).filter(
            models.EmailOTP.email == email.lower()
        ).delete()
        db.commit()
        db.refresh(existing)
        otp = _generate_email_otp(db, existing.email)
        return existing, otp

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
