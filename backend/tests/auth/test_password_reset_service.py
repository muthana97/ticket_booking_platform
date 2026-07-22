from datetime import datetime, timedelta
import pytest
from fastapi import HTTPException

from src.auth import service, models, utils


def _make_verified_user(db, email="alice@example.com", password="OldPass1!"):
    user = models.User(
        email=email,
        password_hash=utils.hash_password(password),
        full_name="Alice Doe",
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_request_password_reset_creates_otp_for_verified_user(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)  # skip real send
    _make_verified_user(db)
    service.request_password_reset(db, email="alice@example.com")
    rows = db.query(models.EmailOTP).filter_by(email="alice@example.com", purpose="reset").all()
    assert len(rows) == 1
    assert len(rows[0].otp_code) == 6


def test_request_password_reset_is_silent_when_user_missing(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    # No user seeded. Should not raise and should not create an OTP row.
    service.request_password_reset(db, email="ghost@example.com")
    rows = db.query(models.EmailOTP).all()
    assert rows == []


def test_request_password_reset_is_silent_when_user_unverified(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    user = _make_verified_user(db)
    user.email_verified = False
    db.commit()
    service.request_password_reset(db, email="alice@example.com")
    rows = db.query(models.EmailOTP).filter_by(purpose="reset").all()
    assert rows == []


def test_confirm_password_reset_updates_hash_and_consumes_otp(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _make_verified_user(db)
    service.request_password_reset(db, email="alice@example.com")
    rec = db.query(models.EmailOTP).filter_by(purpose="reset").first()

    user = service.confirm_password_reset(
        db, email="alice@example.com", otp_code=rec.otp_code, new_password="NewPass9#",
    )
    assert utils.verify_password("NewPass9#", user.password_hash)
    assert not utils.verify_password("OldPass1!", user.password_hash)
    remaining = db.query(models.EmailOTP).filter_by(purpose="reset").all()
    assert remaining == []


def test_confirm_password_reset_wrong_code_raises_generic_400(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _make_verified_user(db)
    service.request_password_reset(db, email="alice@example.com")

    with pytest.raises(HTTPException) as exc:
        service.confirm_password_reset(
            db, email="alice@example.com", otp_code="000000", new_password="NewPass9#",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid or expired code"


def test_confirm_password_reset_expired_otp_rejected(db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _make_verified_user(db)
    service.request_password_reset(db, email="alice@example.com")
    rec = db.query(models.EmailOTP).filter_by(purpose="reset").first()
    rec.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.confirm_password_reset(
            db, email="alice@example.com", otp_code=rec.otp_code, new_password="NewPass9#",
        )
    assert exc.value.status_code == 400


def test_confirm_password_reset_rejects_verify_purpose_otp(db, monkeypatch):
    """A verify-email OTP must NOT be usable to reset a password."""
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _make_verified_user(db)
    # Simulate an outstanding verify OTP (as if the user re-registered).
    verify_otp = models.EmailOTP(
        email="alice@example.com",
        otp_code="123456",
        purpose="verify",
        expires_at=datetime.utcnow() + timedelta(minutes=5),
    )
    db.add(verify_otp)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        service.confirm_password_reset(
            db, email="alice@example.com", otp_code="123456", new_password="NewPass9#",
        )
    assert exc.value.status_code == 400


def test_confirm_password_reset_unknown_email_generic_400(db):
    with pytest.raises(HTTPException) as exc:
        service.confirm_password_reset(
            db, email="ghost@example.com", otp_code="123456", new_password="NewPass9#",
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid or expired code"


def test_request_password_reset_hits_rate_limit(db, monkeypatch):
    """Two requests within 30s → the second raises 429. The shared cooldown
    (keyed on EmailOTP.email) already gives us this — the test just proves
    we didn't accidentally bypass it."""
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _make_verified_user(db)
    service.request_password_reset(db, email="alice@example.com")
    with pytest.raises(HTTPException) as exc:
        service.request_password_reset(db, email="alice@example.com")
    assert exc.value.status_code == 429
