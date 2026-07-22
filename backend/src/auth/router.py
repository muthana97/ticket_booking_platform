from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from . import service, schemas, utils, dependencies as deps

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=schemas.RegisterResponse, status_code=201)
def register(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    """
    Create a new account. Role is chosen here and persisted — it can never be
    changed at sign-in. Customers go to `active`; Providers land in `pending`
    and an Admin must approve them before they can create trips.

    Returns the dev-mode OTP in the response so the demo can prefill it.
    """
    user, dev_otp = service.register_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
        phone_number=payload.phone_number,
        national_id=payload.national_id,
    )
    return {
        "message": "Account created. Check your email for the 6-digit code.",
        "email": user.email,
        "role": user.role,
        "status": user.status,
        # Dev-mode convenience only. Stripped in production to avoid leaking
        # OTPs in API responses. See settings.DEBUG.
        "dev_otp": dev_otp if settings.DEBUG else None,
    }


@router.post("/verify-email", response_model=schemas.TokenResponse)
def verify_email(payload: schemas.VerifyEmailRequest, db: Session = Depends(get_db)):
    """
    Confirm the email OTP. On success the user is flagged `email_verified=true`
    and immediately receives a JWT (no separate login round-trip needed).
    """
    user = service.verify_email(db, email=payload.email, otp_code=payload.otp_code)
    token = utils.create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/resend-otp", response_model=schemas.RegisterResponse)
def resend_otp(payload: schemas.ResendOtpRequest, db: Session = Depends(get_db)):
    """Issue a fresh verification code. Pre-verified accounts get rejected."""
    from . import models  # local to avoid module cycle
    dev_otp = service.resend_email_otp(db, email=payload.email)
    user = db.query(models.User).filter(models.User.email == payload.email.lower()).first()
    return {
        "message": "New verification code issued.",
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "dev_otp": dev_otp if settings.DEBUG else None,
    }


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    """Email + password sign-in. Returns the user record with role + status
    so the frontend can route correctly."""
    user = service.authenticate(db, email=payload.email, password=payload.password)
    token = utils.create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/me", response_model=schemas.UserOut)
def me(current_user=Depends(deps.get_current_user)):
    """Return the current authenticated user (role + status reflect DB truth,
    not the JWT — so admin promotions/blocks take effect immediately)."""
    return current_user


@router.post("/password-reset/request")
def password_reset_request(
    payload: schemas.PasswordResetRequestIn,
    bg: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Silent endpoint: always returns the same generic message, regardless of
    whether the email is known or verified. Rate limit still applies and
    returns a real 429 (same behavior as /auth/resend-otp — the limit itself
    is public info and doesn't leak account existence).

    The actual Resend HTTP call is deferred via BackgroundTasks so the
    response timing doesn't distinguish known/verified emails (slow, real
    HTTP call) from unknown ones (fast, no-op) — see service.request_password_reset.
    """
    service.request_password_reset(db, email=payload.email, bg=bg)
    return {"message": "If an account exists, a reset code has been sent."}


@router.post("/password-reset/confirm", response_model=schemas.TokenResponse)
def password_reset_confirm(
    payload: schemas.PasswordResetConfirmIn, db: Session = Depends(get_db)
):
    """
    Verify the reset OTP and set the new password. On success, auto-signs
    the user in by returning a fresh JWT — same shape as /auth/verify-email
    so the frontend can reuse its "login on success" code path.
    """
    user = service.confirm_password_reset(
        db,
        email=payload.email,
        otp_code=payload.otp_code,
        new_password=payload.new_password,
    )
    token = utils.create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer", "user": user}
