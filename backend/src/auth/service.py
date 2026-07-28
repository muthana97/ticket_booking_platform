import random
from datetime import datetime, timedelta

import httpx
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from . import models, utils


RESEND_URL = "https://api.resend.com/emails"


def _send_email(to: str, subject: str, html: str, text: str) -> bool:
    """
    Deliver an email via Resend's HTTP API. Returns True on 2xx. On failure
    (or missing config) returns False; callers fall back to the console-log
    OTP path, keeping local dev workable without a live key.
    """
    if not (settings.RESEND_API_KEY and settings.RESEND_FROM):
        return False
    try:
        r = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.RESEND_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=15,
        )
        if 200 <= r.status_code < 300:
            print(f"[EMAIL] sent to {to} subject={subject!r} resend_id={r.json().get('id')}")
            return True
        print(f"[EMAIL] Resend rejected: HTTP {r.status_code} body={r.text[:400]}")
        return False
    except Exception as e:
        print(f"[EMAIL] Resend delivery failed: {e!r}")
        return False


def _generate_email_otp(db: Session, email: str) -> str:
    # Rate limit (NFR-08 / ERR-04):
    #   - 30 second cooldown between successive requests for the same email
    #   - max 3 codes per email per hour
    now = datetime.utcnow()
    last = (
        db.query(models.EmailOTP)
        .filter(models.EmailOTP.email == email.lower())
        .order_by(models.EmailOTP.id.desc())
        .first()
    )
    if last is not None:
        elapsed = (now - last.created_at).total_seconds()
        if elapsed < 30:
            wait = int(30 - elapsed) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before requesting another code.",
            )

    hour_ago = now - timedelta(hours=1)
    recent = (
        db.query(models.EmailOTP)
        .filter(
            models.EmailOTP.email == email.lower(),
            models.EmailOTP.created_at > hour_ago,
        )
        .count()
    )
    if recent >= 3:
        raise HTTPException(
            status_code=429,
            detail="Too many verification requests. Try again in an hour.",
        )

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
        # Fallback when Resend isn't configured (or fails) — keeps local dev working.
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
    national_id: str | None = None,
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
        existing.national_id = national_id
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
        national_id=national_id,
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


def _deliver_reset_otp(email: str, subject: str, html: str, text: str, code: str) -> None:
    """Background-task target: send via Resend, fall back to console-log on
    failure. Split out of _generate_password_reset_otp so the HTTP call can
    be deferred with BackgroundTasks — see that function for why."""
    sent = _send_email(to=email, subject=subject, html=html, text=text)
    if not sent:
        print(f"[EMAIL-RESET-CONSOLE] {email} → {code}")


def _generate_password_reset_otp(
    db: Session, email: str, *, bg: BackgroundTasks | None = None
) -> str:
    # Same rate limit as verify-email OTPs — keyed on EmailOTP.email so a
    # spammer flipping between purposes still hits the shared cap.
    now = datetime.utcnow()
    last = (
        db.query(models.EmailOTP)
        .filter(models.EmailOTP.email == email.lower())
        .order_by(models.EmailOTP.id.desc())
        .first()
    )
    if last is not None:
        elapsed = (now - last.created_at).total_seconds()
        if elapsed < 30:
            wait = int(30 - elapsed) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before requesting another code.",
            )

    hour_ago = now - timedelta(hours=1)
    recent = (
        db.query(models.EmailOTP)
        .filter(
            models.EmailOTP.email == email.lower(),
            models.EmailOTP.created_at > hour_ago,
        )
        .count()
    )
    if recent >= 3:
        raise HTTPException(
            status_code=429,
            detail="Too many code requests. Try again in an hour.",
        )

    code = f"{random.randint(100000, 999999)}"
    rec = models.EmailOTP(
        email=email,
        otp_code=code,
        purpose="reset",
        expires_at=datetime.utcnow() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )
    db.add(rec)
    db.commit()

    subject = "Reset your Tazkirati password"
    text = (
        "You (or someone using your email) requested a password reset for your "
        "Tazkirati account.\n\n"
        f"Your 6-digit reset code is: {code}\n"
        f"It expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n\n"
        "If you didn't request this, ignore this email — your password won't change."
    )
    html = f"""\
<!doctype html>
<html><body style="font-family: -apple-system, system-ui, sans-serif; background: #F2EAD3; padding: 32px;">
  <table style="max-width: 480px; margin: 0 auto; background: #FBF6E7; border: 1.5px solid #2D261B;">
    <tr><td style="padding: 28px 32px 14px;">
      <div style="font-family: Georgia, serif; font-weight: 900; font-size: 32px; color: #1A1814; letter-spacing: -0.02em;">Tazkirati.</div>
      <div style="font-family: monospace; font-size: 10px; letter-spacing: 0.2em; color: #3D362A; text-transform: uppercase; margin-top: 4px;">Password Reset</div>
    </td></tr>
    <tr><td style="padding: 0 32px 28px;">
      <p style="font-size: 15px; color: #1A1814; margin: 18px 0;">Enter this code to set a new password:</p>
      <div style="font-family: monospace; font-weight: 600; font-size: 40px; letter-spacing: 0.4em; padding: 18px; background: #F2EAD3; border: 2px solid #0F2A47; color: #0F2A47; text-align: center;">{code}</div>
      <p style="font-size: 12px; color: #3D362A; margin-top: 16px;">Valid for {settings.OTP_EXPIRY_MINUTES} minutes. If you didn't request this, ignore this email — your password won't change.</p>
    </td></tr>
  </table>
</body></html>"""

    if bg is not None:
        bg.add_task(_deliver_reset_otp, email, subject, html, text, code)
    else:
        _deliver_reset_otp(email, subject, html, text, code)
    return code


def request_password_reset(
    db: Session, *, email: str, bg: BackgroundTasks | None = None
) -> None:
    """
    Silent about account existence: returns None whether or not the email
    maps to a verified user, so callers cannot branch on the outcome.
    Emails are only sent when the account exists AND is email-verified AND
    not blocked. Rate-limit exceptions from _generate_password_reset_otp
    (HTTP 429) are NOT swallowed — they propagate so the caller can surface
    the retry hint.

    When `bg` (a FastAPI BackgroundTasks) is supplied, the actual HTTP send
    to Resend is deferred to run AFTER the response is returned — closing a
    timing oracle where a known+verified email took ~100-500ms (live HTTP
    call) but an unknown email returned in microseconds, letting a single
    probe distinguish real accounts from unknown ones. The rate-limit check
    and OTP-row insert (the only foreground-observable side effects) still
    happen synchronously so a 429 still surfaces immediately.
    """
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user or not user.email_verified or user.status == "blocked":
        return
    _generate_password_reset_otp(db, user.email, bg=bg)


def confirm_password_reset(
    db: Session, *, email: str, otp_code: str, new_password: str
) -> models.User:
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    # Deliberate: same error message whether the user, status, or OTP is bad
    # — keeps account-existence (and blocked-status) hidden.
    generic_fail = HTTPException(status_code=400, detail="Invalid or expired code")
    if not user or not user.email_verified or user.status == "blocked":
        raise generic_fail

    rec = (
        db.query(models.EmailOTP)
        .filter(
            models.EmailOTP.email == email.lower(),
            models.EmailOTP.otp_code == otp_code,
            models.EmailOTP.purpose == "reset",
        )
        .order_by(models.EmailOTP.id.desc())
        .first()
    )
    if not rec or rec.expires_at < datetime.utcnow():
        raise generic_fail

    user.password_hash = utils.hash_password(new_password)
    # Invalidate ALL outstanding reset OTPs for this email, not just the one
    # consumed — otherwise a "Resend code" duplicate stays live (replay
    # window) until its own expires_at.
    db.query(models.EmailOTP).filter(
        models.EmailOTP.email == email.lower(),
        models.EmailOTP.purpose == "reset",
    ).delete()
    db.commit()
    db.refresh(user)
    return user


def update_profile(
    db: Session,
    user: models.User,
    *,
    full_name: str | None,
    phone_number: str | None,
    national_id: str | None,
    phone_provided: bool,
    id_provided: bool,
) -> models.User:
    """Partial update of the three self-editable profile columns.

    `phone_provided` / `id_provided` are the router's proof that the caller
    actually included the field in the JSON body (via
    `payload.model_fields_set`). Without them we can't distinguish "leave
    alone" from "set to null" — Pydantic v2 gives us the same `None` for both.
    """
    if full_name is not None:
        user.full_name = full_name.strip()
    if phone_provided:
        user.phone_number = phone_number  # may be None to clear
    if id_provided:
        user.national_id = national_id    # may be None to clear
    db.commit()
    db.refresh(user)
    return user
