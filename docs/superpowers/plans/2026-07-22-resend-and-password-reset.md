# Resend Email Transport + Password Reset — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate email delivery from `smtplib`/SMTP (blocked on Render free tier) to Resend's HTTPS API, then add a full email-OTP password reset flow on top of the new transport.

**Architecture:** Rewrite the private `_send_email()` seam in `backend/src/auth/service.py` to call Resend's `POST /emails` via `httpx`, keeping all existing OTP generation, rate-limit, and console-fallback machinery unchanged. Add two new auth service functions (`request_password_reset`, `confirm_password_reset`) that reuse the existing `EmailOTP` table by extending its `purpose` field from `{"verify"}` to `{"verify", "reset"}` — zero schema migration. Expose them as two new endpoints. On the frontend (`redesign/pillow` branch, v2 file only), add two new pillow-styled screens (`screen-forgot-password`, `screen-reset-password`) and a "Forgot password?" link on `screen-sign-in`.

**Tech Stack:** FastAPI + SQLAlchemy 2.x, Pydantic v2, `httpx` (already a dep; used for Resend HTTP calls and TestClient), pytest 8.3 with in-memory SQLite + `StaticPool` fixtures, vanilla-JS v2 SPA with the existing `I18N` runtime.

## Global Constraints

- **Only touch `frontend/index-v2.html`** on this branch. `frontend/index.html` is a rollback surface and must not be modified. (CLAUDE.md § "Constraints carried into v2")
- **Every new visible string gets both EN and AR keys** in the `I18N` table. Numeric inputs force `direction: ltr` in Arabic mode. (CLAUDE.md § Localization)
- **Backend tests use fresh in-memory SQLite per test** — write tests using the existing `client` / `db` fixtures from `backend/tests/conftest.py`; do not open real connections.
- **HTTP calls in tests must be mocked** via `unittest.mock.patch` on `src.auth.service.httpx.post`. Do NOT add `respx` or any new dependency.
- **Password constraint** on any new reset endpoint: `Field(..., min_length=6, max_length=128)` — matches `RegisterRequest` exactly.
- **OTP constraint** on any new endpoint: `Field(..., min_length=6, max_length=6)` — matches `VerifyEmailRequest` exactly.
- **Response schema for the "signed-in" endpoints** is the existing `schemas.TokenResponse` — do not invent new ones for password-reset confirm.
- **API caller signature on the frontend** is `api(path, {method, body: JSON.stringify(...)})` — NOT `api(method, path, body)`. Getting this wrong silently breaks the call. (CLAUDE.md § Recent fixes, commission UI bug #1)
- **Silent success on missing/unverified accounts** for password reset request — the endpoint must return 200 with the same generic message whether or not the email exists. Do not leak account existence via 404 or via message text.
- **No changes to `frontend/index.html`, no changes to `backend/src/booking/tasks.py`** (Reaper is golden, per CLAUDE.md § Do not modify).
- **Working directory for all commands:** `/Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform`. Backend tests run from `backend/` with `cd backend && python -m pytest ...`.

---

## File Structure

**Backend files to modify:**
- `backend/src/config.py` — swap SMTP_* settings for Resend settings (Task 1)
- `backend/src/auth/service.py` — rewrite `_send_email()`, add three new service functions (Tasks 1 + 2)
- `backend/src/auth/schemas.py` — add `PasswordResetRequestIn` and `PasswordResetConfirmIn` (Task 3)
- `backend/src/auth/router.py` — add two new endpoints (Task 3)

**Backend files to create:**
- `backend/tests/auth/__init__.py` — empty (mirror `tests/booking/__init__.py`)
- `backend/tests/auth/test_send_email_resend.py` — 4 tests for the transport (Task 1)
- `backend/tests/auth/test_password_reset_service.py` — 6 tests for the service functions (Task 2)
- `backend/tests/auth/test_password_reset_endpoints.py` — 4 tests for the endpoints (Task 3)

**Frontend file to modify:**
- `frontend/index-v2.html` — add two screens, sign-in link, i18n keys, JS wiring (Tasks 4 + 5)

**Docs to modify:**
- `CLAUDE.md` — Known Limitations, Deploy from scratch, Upgrade path, Recent fixes (Task 6)

---

## Task 1: Swap SMTP → Resend HTTP transport

**Files:**
- Modify: `backend/src/config.py`
- Modify: `backend/src/auth/service.py`
- Create: `backend/tests/auth/__init__.py`
- Create: `backend/tests/auth/test_send_email_resend.py`

**Interfaces:**
- Produces: `_send_email(to: str, subject: str, html: str, text: str) -> bool` — same signature as before; True on 2xx, False on missing config / non-2xx / exception. Callers (existing + new) do not change.
- Produces: `settings.RESEND_API_KEY: Optional[str]`, `settings.RESEND_FROM: Optional[str]`.

- [ ] **Step 1: Create the tests directory init**

```bash
mkdir -p backend/tests/auth
touch backend/tests/auth/__init__.py
```

- [ ] **Step 2: Write failing tests for the Resend transport**

Create `backend/tests/auth/test_send_email_resend.py`:

```python
from unittest.mock import patch, MagicMock

from src.auth import service


def _mock_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {"id": "resend-msg-abc"}
    resp.text = str(body or "")
    return resp


def test_send_email_returns_false_when_key_missing(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")
    assert service._send_email("to@x.com", "sub", "<b>h</b>", "t") is False


def test_send_email_returns_false_when_from_missing(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_abc")
    monkeypatch.setattr(service.settings, "RESEND_FROM", None)
    assert service._send_email("to@x.com", "sub", "<b>h</b>", "t") is False


def test_send_email_posts_correct_body_and_headers(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <no-reply@tazkirati.app>")

    with patch("src.auth.service.httpx.post", return_value=_mock_response()) as mock_post:
        ok = service._send_email("user@example.com", "Subject", "<b>Hello</b>", "Hello")

    assert ok is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["json"] == {
        "from": "Tazkirati <no-reply@tazkirati.app>",
        "to": ["user@example.com"],
        "subject": "Subject",
        "html": "<b>Hello</b>",
        "text": "Hello",
    }
    assert kwargs["timeout"] == 15


def test_send_email_returns_false_on_non_2xx(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")

    with patch("src.auth.service.httpx.post", return_value=_mock_response(status_code=422, body={"error": "bad"})):
        assert service._send_email("u@x.com", "s", "<b>h</b>", "t") is False


def test_send_email_returns_false_on_exception(monkeypatch):
    monkeypatch.setattr(service.settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(service.settings, "RESEND_FROM", "Tazkirati <x@y.z>")

    with patch("src.auth.service.httpx.post", side_effect=Exception("network down")):
        assert service._send_email("u@x.com", "s", "<b>h</b>", "t") is False
```

- [ ] **Step 3: Run the tests to confirm they fail**

Run:
```bash
cd backend && python -m pytest tests/auth/test_send_email_resend.py -v
```
Expected: All 5 fail (because `settings.RESEND_API_KEY` doesn't exist yet AND because `_send_email` still uses smtplib).

- [ ] **Step 4: Update `backend/src/config.py`**

Replace this block (currently at ~line 47-52):
```python
    # ----- SMTP (optional — if unset we fall back to console-logged OTPs) -----
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None
```

With:
```python
    # ----- Resend (HTTP email API — https://resend.com/docs) -----
    # If unset (or the sender domain isn't verified in Resend), _send_email
    # returns False and OTPs fall back to the [EMAIL-OTP-CONSOLE] server log.
    # This keeps local dev workable without a live API key.
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: Optional[str] = None  # e.g. "Tazkirati <noreply@yourdomain.com>"
```

- [ ] **Step 5: Rewrite `_send_email()` in `backend/src/auth/service.py`**

Delete lines 1-5 (the smtplib + MIME imports):
```python
import random
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
```

Replace with:
```python
import random
from datetime import datetime, timedelta

import httpx
```

Delete the entire existing `_send_email()` function (lines 14-38 in the current file) and replace with:

```python
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
```

- [ ] **Step 6: Run the transport tests to confirm they pass**

Run:
```bash
cd backend && python -m pytest tests/auth/test_send_email_resend.py -v
```
Expected: All 5 PASS.

- [ ] **Step 7: Run the full backend suite to confirm no regressions**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: All existing tests still pass (existing OTP tests do not exercise the transport — `_send_email` returns False in tests, OTPs fall through to console log, and test assertions read `dev_otp` from responses instead).

- [ ] **Step 8: Commit**

```bash
git add backend/src/config.py backend/src/auth/service.py backend/tests/auth/__init__.py backend/tests/auth/test_send_email_resend.py
git commit -m "$(cat <<'EOF'
feat(auth): swap smtplib -> Resend HTTP API for OTP delivery

SMTP is blocked on Render free tier (ports 25/587/465 outbound denied),
which meant no user actually received an OTP in prod. Resend uses plain
HTTPS which the free tier allows. Same _send_email() seam, same console
fallback when key is unset; existing OTP flow tests are unaffected.

Requires RESEND_API_KEY + RESEND_FROM in Render env; drop the 5 SMTP_*
vars. Sender domain must be verified in the Resend dashboard.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Password reset service functions

**Files:**
- Modify: `backend/src/auth/service.py`
- Create: `backend/tests/auth/test_password_reset_service.py`

**Interfaces:**
- Consumes: `_send_email()` from Task 1.
- Consumes: `_generate_email_otp()` pattern for HTML template + rate limit (`EmailOTP.email` keyed cooldown at 30s + 3/hour cap).
- Produces:
  - `_generate_password_reset_otp(db: Session, email: str) -> str` — returns the 6-digit code; creates `EmailOTP(email=..., otp_code=..., purpose="reset", ...)`; enforces the shared rate limit; sends email via `_send_email`; falls back to `[EMAIL-OTP-CONSOLE]` log on transport failure.
  - `request_password_reset(db: Session, *, email: str) -> None` — silent; only fires when user exists AND `email_verified=True`.
  - `confirm_password_reset(db: Session, *, email: str, otp_code: str, new_password: str) -> models.User` — validates OTP with `purpose="reset"`, updates `password_hash`, deletes the OTP row, returns the refreshed user.

- [ ] **Step 1: Write failing tests for the service layer**

Create `backend/tests/auth/test_password_reset_service.py`:

```python
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
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run:
```bash
cd backend && python -m pytest tests/auth/test_password_reset_service.py -v
```
Expected: All 9 fail with `AttributeError: module 'src.auth.service' has no attribute 'request_password_reset'` (or similar for `_generate_password_reset_otp` / `confirm_password_reset`).

- [ ] **Step 3: Add the three new service functions**

Append to `backend/src/auth/service.py` (after `authenticate()`, at the end of the file):

```python
def _generate_password_reset_otp(db: Session, email: str) -> str:
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
            detail="Too many verification requests. Try again in an hour.",
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

    sent = _send_email(to=email, subject=subject, html=html, text=text)
    if not sent:
        print(f"[EMAIL-RESET-CONSOLE] {email} → {code}")
    return code


def request_password_reset(db: Session, *, email: str) -> None:
    """
    Silent by design: always returns None. Callers must NOT branch on the
    outcome (leaks account existence). Emails are only sent when the account
    exists AND is email-verified.
    """
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    if not user or not user.email_verified:
        return
    _generate_password_reset_otp(db, user.email)


def confirm_password_reset(
    db: Session, *, email: str, otp_code: str, new_password: str
) -> models.User:
    user = db.query(models.User).filter(models.User.email == email.lower()).first()
    # Deliberate: same error message whether the user or the OTP is bad —
    # keeps account-existence hidden.
    generic_fail = HTTPException(status_code=400, detail="Invalid or expired code")
    if not user or not user.email_verified:
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
    db.delete(rec)
    db.commit()
    db.refresh(user)
    return user
```

- [ ] **Step 4: Run the service tests to confirm they pass**

Run:
```bash
cd backend && python -m pytest tests/auth/test_password_reset_service.py -v
```
Expected: All 9 PASS.

- [ ] **Step 5: Run the full backend suite for regressions**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: All existing tests still pass. Suite grows by 9 (was 96 → now 105).

- [ ] **Step 6: Commit**

```bash
git add backend/src/auth/service.py backend/tests/auth/test_password_reset_service.py
git commit -m "$(cat <<'EOF'
feat(auth): password reset service layer

Adds _generate_password_reset_otp (mirror of verify-email OTP with
purpose='reset'), request_password_reset (silent — never leaks account
existence), and confirm_password_reset. Reuses the existing EmailOTP
table by extending the purpose field from {'verify'} to {'verify','reset'}
— no schema migration needed. Shares the same 30s + 3/hour rate limit
with the verify-email flow.

9 new tests covering happy path, unknown email, unverified account,
wrong OTP, expired OTP, cross-purpose OTP rejection, rate limit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Password reset endpoints

**Files:**
- Modify: `backend/src/auth/schemas.py`
- Modify: `backend/src/auth/router.py`
- Create: `backend/tests/auth/test_password_reset_endpoints.py`

**Interfaces:**
- Consumes: `service.request_password_reset()` and `service.confirm_password_reset()` from Task 2.
- Consumes: `utils.create_access_token()`, existing `schemas.TokenResponse`.
- Produces:
  - `POST /auth/password-reset/request` — body `PasswordResetRequestIn`, returns dict `{"message": "..."}`.
  - `POST /auth/password-reset/confirm` — body `PasswordResetConfirmIn`, returns `schemas.TokenResponse`.

- [ ] **Step 1: Write failing endpoint tests**

Create `backend/tests/auth/test_password_reset_endpoints.py`:

```python
from unittest.mock import patch

from src.auth import service, models, utils


def _seed_verified_user(db, email="bob@example.com", password="OldPass1!"):
    user = models.User(
        email=email,
        password_hash=utils.hash_password(password),
        full_name="Bob Doe",
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_request_endpoint_returns_200_and_generic_message(client, db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _seed_verified_user(db)
    r = client.post("/auth/password-reset/request", json={"email": "bob@example.com"})
    assert r.status_code == 200
    assert r.json() == {"message": "If an account exists, a reset code has been sent."}


def test_request_endpoint_returns_200_for_unknown_email(client):
    r = client.post("/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert r.status_code == 200
    assert r.json() == {"message": "If an account exists, a reset code has been sent."}


def test_confirm_endpoint_happy_path_signs_user_in(client, db, monkeypatch):
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _seed_verified_user(db)
    client.post("/auth/password-reset/request", json={"email": "bob@example.com"})
    otp = db.query(models.EmailOTP).filter_by(purpose="reset").first().otp_code

    r = client.post(
        "/auth/password-reset/confirm",
        json={"email": "bob@example.com", "otp_code": otp, "new_password": "NewPass9#"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "bob@example.com"

    # Old password no longer works; new one does.
    r2 = client.post("/auth/login", json={"email": "bob@example.com", "password": "OldPass1!"})
    assert r2.status_code == 401
    r3 = client.post("/auth/login", json={"email": "bob@example.com", "password": "NewPass9#"})
    assert r3.status_code == 200


def test_confirm_endpoint_rejects_short_password(client, db, monkeypatch):
    """Pydantic schema enforces min_length=6 — a 5-char password 422s before
    the service ever runs, matching RegisterRequest behavior."""
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _seed_verified_user(db)
    client.post("/auth/password-reset/request", json={"email": "bob@example.com"})
    otp = db.query(models.EmailOTP).filter_by(purpose="reset").first().otp_code

    r = client.post(
        "/auth/password-reset/confirm",
        json={"email": "bob@example.com", "otp_code": otp, "new_password": "short"},
    )
    assert r.status_code == 422


def test_pre_reset_session_tokens_remain_valid(client, db, monkeypatch):
    """Documents current MVP behavior: existing JWTs are NOT invalidated on
    password reset. Tokens naturally expire after ACCESS_TOKEN_EXPIRE_MINUTES.
    If this becomes a hardening priority, this test flips to assert 401."""
    monkeypatch.setattr(service, "_send_email", lambda **kw: False)
    _seed_verified_user(db)
    # Sign in and grab the pre-reset token.
    login_resp = client.post(
        "/auth/login", json={"email": "bob@example.com", "password": "OldPass1!"}
    )
    assert login_resp.status_code == 200
    pre_token = login_resp.json()["access_token"]

    # Reset the password.
    client.post("/auth/password-reset/request", json={"email": "bob@example.com"})
    otp = db.query(models.EmailOTP).filter_by(purpose="reset").first().otp_code
    reset_resp = client.post(
        "/auth/password-reset/confirm",
        json={"email": "bob@example.com", "otp_code": otp, "new_password": "NewPass9#"},
    )
    assert reset_resp.status_code == 200

    # Old token still works against /auth/me.
    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {pre_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "bob@example.com"
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:
```bash
cd backend && python -m pytest tests/auth/test_password_reset_endpoints.py -v
```
Expected: All 5 fail with 404 (endpoints don't exist yet).

- [ ] **Step 3: Add the two new schemas**

Append to `backend/src/auth/schemas.py`:

```python
# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    email: EmailStr
    otp_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)
```

- [ ] **Step 4: Add the two new endpoints**

Append to `backend/src/auth/router.py` (after the `/me` endpoint at the bottom):

```python
@router.post("/password-reset/request")
def password_reset_request(
    payload: schemas.PasswordResetRequestIn, db: Session = Depends(get_db)
):
    """
    Silent endpoint: always returns the same generic message, regardless of
    whether the email is known or verified. Rate limit still applies and
    returns a real 429 (same behavior as /auth/resend-otp — the limit itself
    is public info and doesn't leak account existence).
    """
    service.request_password_reset(db, email=payload.email)
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
```

- [ ] **Step 5: Run endpoint tests to confirm they pass**

Run:
```bash
cd backend && python -m pytest tests/auth/test_password_reset_endpoints.py -v
```
Expected: All 5 PASS.

- [ ] **Step 6: Run the full backend suite for regressions**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: All tests pass. Suite grows by 5 (105 → 110).

- [ ] **Step 7: Commit**

```bash
git add backend/src/auth/schemas.py backend/src/auth/router.py backend/tests/auth/test_password_reset_endpoints.py
git commit -m "$(cat <<'EOF'
feat(auth): password reset endpoints

POST /auth/password-reset/request (silent — always 200 with the same
generic message) and POST /auth/password-reset/confirm (returns
TokenResponse, auto-signing the user in on success — mirrors the
verify-email flow ergonomics).

5 new endpoint tests covering silent success on unknown emails, happy
path with auto-sign-in verified via /auth/login, short-password 422,
and pre-reset session tokens remaining valid (MVP behavior).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Frontend — forgot-password screen + sign-in link

**Files:**
- Modify: `frontend/index-v2.html`

**Interfaces:**
- Consumes: `POST /auth/password-reset/request` (Task 3), `api()` wrapper, `goto()` state machine, `I18N` runtime, existing `.p-pillow` / `.p-field` / `.p-input` / `.p-cta` CSS primitives, `toast()` helper.
- Produces: New screen id `screen-forgot-password`; new `STATE.pendingResetEmail` string (read by Task 5); new link `#goto-forgot` on sign-in screen; 6 new i18n keys.

- [ ] **Step 1: Add "Forgot password?" link on sign-in screen**

In `frontend/index-v2.html`, locate `<section class="screen" id="screen-sign-in">` (~line 5847). Inside its `.auth-stage` block, find the closing `</div>` of `.p-pillow` (the block containing the email + password fields). Immediately AFTER the closing `</div>` of `.p-pillow` and BEFORE `<button class="cta p-cta" id="sign-in-btn" ...>`, insert:

```html
          <div class="helper" style="margin-top: 10px; text-align: end;">
            <a href="#" id="goto-forgot" class="text-link" data-i18n="auth.signin.forgot_link">Forgot password?</a>
          </div>
```

- [ ] **Step 2: Add the forgot-password screen markup**

In `frontend/index-v2.html`, insert a new `<section>` immediately AFTER the closing `</section>` of `#screen-sign-in` (before `<!-- Register -->`):

```html
    <!-- Forgot password -->
    <section class="screen" id="screen-forgot-password">
      <div class="auth-stage">
        <h1 data-i18n="auth.forgot.title">Reset your password.</h1>
        <div class="lead" data-i18n="auth.forgot.subtitle">Enter your email and we'll send you a 6-digit reset code.</div>
        <div class="p-pillow">
          <div class="p-field">
            <label for="fp-email" data-i18n="form.email">Email</label>
            <div class="p-input">
              <span class="lead-icon" aria-hidden="true">✉︎</span>
              <input type="email" id="fp-email" autocomplete="email" data-i18n-placeholder="auth.forgot.email_placeholder" placeholder="you@example.com" />
            </div>
          </div>
        </div>
        <button class="cta p-cta" id="forgot-btn" data-i18n="auth.forgot.cta">Send reset code →</button>
        <div class="helper" data-i18n="auth.forgot.back" data-i18n-html="1"><a href="#" id="goto-signin-from-forgot" class="text-link">← Back to sign in</a></div>
      </div>
    </section>
```

- [ ] **Step 3: Register the new screen in the CSS body-selector chain**

Locate the block near line ~801-806 that reads:
```css
  body[data-screen="welcome"]               #screen-welcome,
  body[data-screen="sign-in"]               #screen-sign-in,
  body[data-screen="register"]              #screen-register,
  body[data-screen="verify-email"]          #screen-verify-email,
```

Add a line for the new screen (immediately after `verify-email`):
```css
  body[data-screen="forgot-password"]       #screen-forgot-password,
```

(If a similar visibility chain exists elsewhere in the file — grep for `screen-verify-email` — apply the same addition wherever `#screen-verify-email` appears alongside its siblings.)

- [ ] **Step 4: Add 6 new i18n keys**

Grep for `signin.title` in `frontend/index-v2.html` to find the `I18N` table. Add these 6 keys to BOTH the `en:` and `ar:` sub-objects:

**English (`en:`):**
```js
    "auth.signin.forgot_link": "Forgot password?",
    "auth.forgot.title": "Reset your password.",
    "auth.forgot.subtitle": "Enter your email and we'll send you a 6-digit reset code.",
    "auth.forgot.email_placeholder": "you@example.com",
    "auth.forgot.cta": "Send reset code →",
    "auth.forgot.back": "<a href=\"#\" id=\"goto-signin-from-forgot\" class=\"text-link\">← Back to sign in</a>",
```

**Arabic (`ar:`):**
```js
    "auth.signin.forgot_link": "نسيت كلمة المرور؟",
    "auth.forgot.title": "إعادة تعيين كلمة المرور.",
    "auth.forgot.subtitle": "أدخل بريدك الإلكتروني وسنرسل لك رمزاً مكوّناً من 6 أرقام.",
    "auth.forgot.email_placeholder": "أنت@مثال.com",
    "auth.forgot.cta": "إرسال رمز الإعادة →",
    "auth.forgot.back": "<a href=\"#\" id=\"goto-signin-from-forgot\" class=\"text-link\">→ العودة إلى تسجيل الدخول</a>",
```

- [ ] **Step 5: Wire the sign-in "Forgot password?" link**

Grep for `goto-register` in `frontend/index-v2.html` — you'll find its click handler in the JS block (looks like `$('#goto-register').addEventListener('click', ...)` or similar). Immediately AFTER that handler, add:

```js
    // "Forgot password?" link on sign-in → forgot-password screen
    $('#goto-forgot').addEventListener('click', (e) => {
      e.preventDefault();
      goto('forgot-password');
    });
```

- [ ] **Step 6: Wire the forgot-password submit + back link**

Grep for `sign-in-btn` in the JS block to find the sign-in submit handler for a reference pattern. Add these two handlers alongside it:

```js
    // Forgot password: send reset code
    $('#forgot-btn').addEventListener('click', async () => {
      const email = ($('#fp-email').value || '').trim().toLowerCase();
      if (!email) { toast(t('toast.forgot.email_required')); return; }
      $('#forgot-btn').disabled = true;
      try {
        await api('/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({ email }),
        });
        STATE.pendingResetEmail = email;
        toast(t('toast.forgot.sent'));
        goto('reset-password');
      } catch (err) {
        toast(err.message || t('toast.generic_error'));
      } finally {
        $('#forgot-btn').disabled = false;
      }
    });

    // Back to sign-in from forgot-password
    $('#goto-signin-from-forgot').addEventListener('click', (e) => {
      e.preventDefault();
      goto('sign-in');
    });
```

Add two additional i18n keys — the toast strings referenced above:

**English:**
```js
    "toast.forgot.email_required": "Enter your email first",
    "toast.forgot.sent": "Check your email for a reset code",
```

**Arabic:**
```js
    "toast.forgot.email_required": "أدخل بريدك الإلكتروني أولاً",
    "toast.forgot.sent": "تحقّق من بريدك للحصول على رمز الإعادة",
```

(If `t('toast.generic_error')` doesn't already exist in the table, grep for its use elsewhere — it should be pre-existing. If genuinely missing, add `"toast.generic_error": "Something went wrong"` / `"حدث خطأ ما"`.)

- [ ] **Step 7: Add `pendingResetEmail` to the STATE initializer**

Grep for `pendingResetEmail` (should be absent). Then grep for the `STATE = {` object declaration. Add the new key alongside similar transient state keys:

```js
      pendingResetEmail: null,
```

- [ ] **Step 8: Manual smoke test**

Start the backend and open v2 in a browser (per CLAUDE.md the backend serves v2 by default on `feat/mobile-scaffold`):
```bash
cd backend && uvicorn src.main:app --reload
```
Open `http://localhost:8000/app/` and:
1. Land on Welcome → click Sign in → "Forgot password?" link is visible under the password field.
2. Click it → routes to the forgot-password screen with email input + amber "Send reset code" CTA.
3. Enter `passenger@tazkirati.app` and click send → toast appears; screen routes to a not-yet-existent `reset-password` screen (Task 5 lands the target — for this task you'll see a blank/broken screen after routing, which is expected).
4. Server console shows `[EMAIL-RESET-CONSOLE] passenger@tazkirati.app → NNNNNN` (Resend key not set locally, so it falls back to console log). Note the code — you'll use it in Task 5's smoke test.
5. Toggle to Arabic (EN/عربي toggle in the topbar) and confirm the forgot-password screen renders in Arabic with RTL layout.

- [ ] **Step 9: Commit**

```bash
git add frontend/index-v2.html
git commit -m "$(cat <<'EOF'
feat(v2): forgot-password screen + sign-in entry point

Adds screen-forgot-password (pillow-styled email input + amber CTA + back
link) and a "Forgot password?" link under the password field on the
sign-in screen. On submit calls POST /auth/password-reset/request
(silent — same 200 whether or not the email is known) and stashes the
email in STATE.pendingResetEmail for the reset screen to read.

8 new i18n keys (EN + AR).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend — reset-password screen

**Files:**
- Modify: `frontend/index-v2.html`

**Interfaces:**
- Consumes: `POST /auth/password-reset/confirm` (Task 3), `STATE.pendingResetEmail` (Task 4), `api()` wrapper, `goto()` state machine, `I18N` runtime, existing pillow primitives, `toast()` helper, existing `paintChrome()` + `STATE.auth` pattern from the verify-email success path.
- Produces: New screen id `screen-reset-password`; ~9 new i18n keys.

- [ ] **Step 1: Add the reset-password screen markup**

In `frontend/index-v2.html`, insert a new `<section>` immediately AFTER the `</section>` of `#screen-forgot-password` (from Task 4) and BEFORE `<!-- Register -->`:

```html
    <!-- Reset password -->
    <section class="screen" id="screen-reset-password">
      <div class="auth-stage">
        <h1 data-i18n="auth.reset.title">Enter your new password.</h1>
        <div class="lead"><span data-i18n="auth.reset.subtitle">Enter the 6-digit code we sent to</span> <b id="rp-email">—</b>.</div>
        <div class="p-pillow">
          <div class="p-field">
            <label for="rp-otp" data-i18n="auth.reset.otp_placeholder">6-digit code</label>
            <div class="p-input">
              <span class="lead-icon" aria-hidden="true">🔑</span>
              <input type="text" id="rp-otp" inputmode="numeric" maxlength="6" class="otp-input" placeholder="••••••" style="direction: ltr;" />
            </div>
          </div>
          <div class="p-field">
            <label for="rp-password" data-i18n="auth.reset.new_password">New password</label>
            <div class="p-input">
              <span class="lead-icon" aria-hidden="true">🔒</span>
              <input type="password" id="rp-password" autocomplete="new-password" />
            </div>
          </div>
          <div class="p-field">
            <label for="rp-password-confirm" data-i18n="auth.reset.confirm_password">Confirm new password</label>
            <div class="p-input">
              <span class="lead-icon" aria-hidden="true">🔒</span>
              <input type="password" id="rp-password-confirm" autocomplete="new-password" />
            </div>
          </div>
        </div>
        <button class="cta p-cta" id="reset-btn" data-i18n="auth.reset.cta">Reset password →</button>
        <button class="cta ghost" id="reset-resend-btn" style="margin-top: 10px;" data-i18n="auth.reset.resend">Resend code</button>
      </div>
    </section>
```

- [ ] **Step 2: Register the screen in the CSS body-selector chain**

Same block modified in Task 4 (line ~801). Add:
```css
  body[data-screen="reset-password"]        #screen-reset-password,
```
immediately after the `forgot-password` line added in Task 4.

- [ ] **Step 3: Add 9 new i18n keys**

**English (`en:`):**
```js
    "auth.reset.title": "Enter your new password.",
    "auth.reset.subtitle": "Enter the 6-digit code we sent to",
    "auth.reset.otp_placeholder": "6-digit code",
    "auth.reset.new_password": "New password",
    "auth.reset.confirm_password": "Confirm new password",
    "auth.reset.cta": "Reset password →",
    "auth.reset.resend": "Resend code",
    "toast.reset.mismatch": "Passwords don't match",
    "toast.reset.success": "Password reset — you're signed in",
```

**Arabic (`ar:`):**
```js
    "auth.reset.title": "أدخل كلمة المرور الجديدة.",
    "auth.reset.subtitle": "أدخل الرمز المكوّن من 6 أرقام الذي أرسلناه إلى",
    "auth.reset.otp_placeholder": "رمز مكوّن من 6 أرقام",
    "auth.reset.new_password": "كلمة المرور الجديدة",
    "auth.reset.confirm_password": "تأكيد كلمة المرور الجديدة",
    "auth.reset.cta": "إعادة تعيين كلمة المرور ←",
    "auth.reset.resend": "إعادة إرسال الرمز",
    "toast.reset.mismatch": "كلمتا المرور غير متطابقتين",
    "toast.reset.success": "تم إعادة التعيين — لقد تم تسجيل دخولك",
```

- [ ] **Step 4: Wire the reset screen JS**

Grep for `verify-btn` in `frontend/index-v2.html` to find the verify-email success handler for a reference pattern (specifically for the `STATE.auth = ...; paintChrome(); goto(...)` chain). Alongside the forgot-password handlers added in Task 4, add:

```js
    // Populate the email display when entering the reset screen.
    // Add this call inside the goto('reset-password') branch of the goto()
    // switch — grep for existing 'verify-email' branches to see the pattern.
    // The one-liner to add:
    //   $('#rp-email').textContent = STATE.pendingResetEmail || '—';

    // Reset password: confirm OTP + set new password
    $('#reset-btn').addEventListener('click', async () => {
      const email = STATE.pendingResetEmail;
      const otp_code = ($('#rp-otp').value || '').trim();
      const new_password = $('#rp-password').value || '';
      const confirm = $('#rp-password-confirm').value || '';
      if (!email) { goto('forgot-password'); return; }
      if (new_password !== confirm) { toast(t('toast.reset.mismatch')); return; }
      $('#reset-btn').disabled = true;
      try {
        const body = await api('/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({ email, otp_code, new_password }),
        });
        // Same success pattern as verify-email: stash auth, paint chrome, route.
        STATE.auth = { token: body.access_token, user: body.user };
        await tazStore.saveAuth(STATE.auth);
        STATE.pendingResetEmail = null;
        $('#rp-otp').value = '';
        $('#rp-password').value = '';
        $('#rp-password-confirm').value = '';
        toast(t('toast.reset.success'));
        paintChrome();
        // Route by role — same logic as the verify-email success handler;
        // grep for `body.user.role === 'admin'` in the verify branch and
        // mirror it here.
        const role = body.user.role;
        const status = body.user.status;
        if (role === 'admin') goto('admin-home');
        else if (role === 'provider' && status === 'active') goto('provider-home');
        else if (role === 'provider') goto('provider-pending');
        else goto('customer-category');
      } catch (err) {
        toast(err.message || t('toast.reset.invalid_code') || 'Invalid or expired code');
      } finally {
        $('#reset-btn').disabled = false;
      }
    });

    // Resend a reset code (reuses the existing /auth/password-reset/request endpoint).
    $('#reset-resend-btn').addEventListener('click', async () => {
      const email = STATE.pendingResetEmail;
      if (!email) { goto('forgot-password'); return; }
      $('#reset-resend-btn').disabled = true;
      try {
        await api('/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({ email }),
        });
        toast(t('toast.forgot.sent'));
      } catch (err) {
        toast(err.message || 'Please wait before requesting another code');
      } finally {
        // Re-enable after 30s to mirror the backend cooldown. If a shared
        // countdown helper already exists (grep for the verify-email resend
        // button handler at #resend-btn), use it here too and swap the
        // hardcoded 30_000 for the shared helper.
        setTimeout(() => { $('#reset-resend-btn').disabled = false; }, 30_000);
      }
    });
```

Also add the `toast.reset.invalid_code` fallback to the i18n table:

**English:**
```js
    "toast.reset.invalid_code": "Invalid or expired code",
```

**Arabic:**
```js
    "toast.reset.invalid_code": "رمز غير صالح أو منتهي الصلاحية",
```

- [ ] **Step 5: Populate `#rp-email` on screen entry**

Grep for `screen-verify-email` in the `goto()` switch/router in the JS block to see how per-screen entry hooks are written. Mirror the pattern for `reset-password`: when the router activates that screen id, run `$('#rp-email').textContent = STATE.pendingResetEmail || '—';`. This is a one-liner in the existing `goto()` case block.

- [ ] **Step 6: Manual smoke test — full password reset flow**

Restart the backend if you stopped it:
```bash
cd backend && uvicorn src.main:app --reload
```

In the browser at `http://localhost:8000/app/`:
1. Sign in as `passenger@tazkirati.app` (any password — you'll change it in this flow anyway, but noting the current one so you can verify old-password rejection).
2. Sign out from the customer chrome.
3. Sign-in screen → click "Forgot password?" → enter `passenger@tazkirati.app` → click "Send reset code".
4. Server console prints `[EMAIL-RESET-CONSOLE] passenger@tazkirati.app → NNNNNN`. Copy the 6-digit code.
5. On the reset-password screen: paste the code, enter `NewDemo#2026` twice, click "Reset password".
6. Should see the success toast and auto-route to `customer-category`.
7. Sign out. Try to sign in with the OLD password → should fail with `Verify your email…` / `Invalid credentials`. Try with `NewDemo#2026` → should succeed.
8. Confirm mismatched password toast: enter mismatched new/confirm → toast fires without a network call.
9. Confirm Arabic RTL: toggle to Arabic, walk through the same flow, confirm OTP input stays LTR (numeric) and all labels + toasts are Arabic.

- [ ] **Step 7: Commit**

```bash
git add frontend/index-v2.html
git commit -m "$(cat <<'EOF'
feat(v2): reset-password screen + auto-sign-in on success

Adds screen-reset-password (pillow-styled three-field form: OTP + new
password + confirm) and its resend link. On submit calls POST
/auth/password-reset/confirm and — mirroring the verify-email success
path — stashes the returned JWT + user into STATE.auth, calls
paintChrome(), and routes by role (admin -> admin-home,
provider/active -> provider-home, provider/pending ->
provider-pending, customer -> customer-category).

Client-side password mismatch check (fails without a network call).
9 new i18n keys (EN + AR); OTP input forced to direction: ltr in RTL.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Docs — CLAUDE.md updates

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** None — pure docs.

- [ ] **Step 1: Update the Known Limitations table**

In `CLAUDE.md`, find the row:
```
| Outbound SMTP blocked (port 25 / 587 / 465) on Render free tier | Email OTP `_send_email()` returns `[EMAIL] SMTP delivery failed: OSError(101, 'Network is unreachable')`. Falls back to `[EMAIL-OTP-CONSOLE]` log line. Users can't verify via email. | (a) Upgrade to Render Starter, or (b) switch from SMTP to an HTTP-API email service (Resend / SendGrid / Mailgun). Resend is the easiest swap. |
```

Replace it with:
```
| Resend sender domain not verified | Until the sender domain has SPF/DKIM DNS records set + verified in the Resend dashboard, Resend only delivers to the account owner's email. Other recipients silently drop. | Complete domain verification in the Resend dashboard. Until then, `_send_email` falls back to the `[EMAIL-OTP-CONSOLE]` log line for unverified recipients — app doesn't crash. |
```

- [ ] **Step 2: Update the "Deploy from scratch" env-var list**

Find this bullet under step 4:
```
   - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` (optional — see Known Limitations)
```

Replace with:
```
   - `RESEND_API_KEY` + `RESEND_FROM` (required for OTP email delivery; get the key from resend.com; format `RESEND_FROM="Tazkirati <noreply@yourdomain.com>"` with a domain verified in Resend)
```

- [ ] **Step 3: Update the "Upgrade path" bullet**

Find this bullet:
```
- Outbound SMTP unblocks on Render Starter.
```

Delete it — no longer relevant since Resend uses plain HTTPS that works on the free tier.

- [ ] **Step 4: Add a Recent Fixes entry**

At the TOP of the `## 🐛 Recent fixes (most recent first)` list (immediately after the section heading), add:

```markdown
- **Email transport swap smtplib → Resend HTTP API + password reset (2026-07-22)**: (1) `_send_email()` in `backend/src/auth/service.py` rewritten to POST Resend's `/emails` endpoint via `httpx` — unblocks OTP delivery on Render's free tier (outbound SMTP was blocked; every OTP had been falling through to the `[EMAIL-OTP-CONSOLE]` log since launch). Config swap: five `SMTP_*` env vars → two `RESEND_API_KEY` + `RESEND_FROM`. Same seam, same console fallback when key is unset — local dev unaffected. 5 new transport tests via `unittest.mock.patch("src.auth.service.httpx.post")`. (2) Password reset flow: extends the existing `EmailOTP` table by adding `"reset"` as a second valid `purpose` value (no schema migration). Two new endpoints — `POST /auth/password-reset/request` (silent — always 200 with generic message, never leaks account existence; rate limit still 429s) and `POST /auth/password-reset/confirm` (returns `TokenResponse`, auto-signing the user in on success). Two new v2/pillow frontend screens on `redesign/pillow` — `screen-forgot-password` (email input + amber "Send reset code" CTA + link on sign-in) and `screen-reset-password` (6-digit code + new password + confirm, client-side mismatch check). 19 new backend tests (110 total). 18 new EN + AR i18n keys. Spec: `docs/superpowers/specs/2026-07-22-resend-and-password-reset-design.md`, plan: `docs/superpowers/plans/2026-07-22-resend-and-password-reset.md`.
```

- [ ] **Step 5: Verify no `SMTP_` references remain**

Run:
```bash
grep -n "SMTP_" CLAUDE.md
```
Expected: No matches. If any remain, evaluate case-by-case and remove or update.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude.md): document Resend swap + password reset

Updates Known Limitations (SMTP row -> Resend domain-verification row),
Deploy from scratch env vars (SMTP_* -> RESEND_*), removes the stale
"SMTP unblocks on Render Starter" upgrade bullet, and adds a Recent
Fixes entry describing the full change.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Full backend suite**

Run:
```bash
cd backend && python -m pytest -q
```
Expected: 110 tests pass (96 before + 5 transport + 9 reset service + 5 reset endpoints = net +19; adjust if grep shows any preexisting `smtplib`-mocking tests that need updating).

- [ ] **Grep confirms SMTP is fully removed from backend**

Run:
```bash
grep -rn "smtplib\|SMTP_HOST\|SMTP_USER\|SMTP_PASSWORD\|SMTP_FROM\|SMTP_PORT" backend/src/
```
Expected: No matches.

- [ ] **Grep confirms v1 is untouched**

Run:
```bash
git diff main -- frontend/index.html
```
Expected: No diff (or exit 0 with no output).

- [ ] **Final commit-level review**

Run:
```bash
git log --oneline main..HEAD
```
Expected: 6 commits landed in order — transport swap, reset service, reset endpoints, forgot-password screen, reset-password screen, docs. Each independently reviewable and rollback-safe.
