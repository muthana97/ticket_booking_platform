# Resend Email Transport + Password Reset — Design Spec

**Date:** 2026-07-22
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)
**Branch:** `redesign/pillow` (v2 frontend surface); backend changes are branch-agnostic
**Related:** Known Limitations table in `CLAUDE.md` (SMTP blocked on Render free tier); AUTH-01 / P-AUTH-01 (phone-OTP still deferred — this spec stays on email)

## 1. Goal

Two connected changes:

1. **Swap the email transport** from `smtplib`-over-SMTP to **Resend's HTTP API**. SMTP is blocked on Render's free tier (port 25/587/465 outbound denied), which meant no user has actually received an email in production since launch — every OTP fell back to the `[EMAIL-OTP-CONSOLE]` server-log line. Resend uses plain HTTPS (`POST api.resend.com/emails`) which the free tier allows, unblocking real email delivery without a paid Render upgrade.
2. **Introduce a password-reset flow** on top of the new transport. Reuses the existing `EmailOTP` table + rate-limit machinery, extends the `purpose` field from `{"verify"}` to `{"verify", "reset"}`, adds two backend endpoints and two v2 frontend screens.

Both changes ship together in one plan.

## 2. Out of scope

- Phone-OTP login (AUTH-01 / P-AUTH-01) — still deferred.
- Password strength policy changes — the reset endpoint accepts whatever `register` accepts.
- Backfilling notifications when a password is reset — not a user-visible event beyond the reset itself.
- Multi-email-provider abstraction. Resend is the only supported transport; if we ever need SendGrid/Mailgun the same `send_email()` seam can be pointed at another API in one PR.
- Rotating a user's active session tokens on password reset. Existing JWTs remain valid until natural expiry (24h). Acceptable for MVP; noted as a future hardening item.
- HTML template overhaul. Password reset reuses the existing pillow-branded verify-email HTML with the copy swapped.
- Native mobile UX for the reset flow. Capacitor wrap picks up the v2 web changes for free once mobile is repointed at `index-v2.html`; no separate native work in this spec.

## 3. Architecture overview

```
                        ┌─────────────────────────────────┐
                        │  Resend HTTPS API               │
                        │  POST api.resend.com/emails     │
                        └────────────▲────────────────────┘
                                     │  bearer token
                                     │
             ┌───────────────────────┴─────────────────────┐
             │  auth/service.py :: _send_email()           │
             │  (httpx.post, returns bool, console-fallback│
             │   when RESEND_API_KEY is unset)             │
             └───────▲─────────────────────────▲───────────┘
                     │                         │
     _generate_email_otp()          _generate_password_reset_otp()
       purpose="verify"                 purpose="reset"
                     │                         │
     ┌───────────────┴───┐         ┌───────────┴──────────────┐
     │ POST /auth/       │         │ POST /auth/              │
     │   register        │         │   password-reset/request │
     │   resend-otp      │         │   password-reset/confirm │
     └───────────────────┘         └──────────────────────────┘
```

Nothing changes about how OTPs are minted, stored, or rate-limited — the two flows share the exact same `EmailOTP` row shape, just distinguished by `purpose`.

## 4. Part 1 — Resend transport

### 4.1 Config changes (`backend/src/config.py`)

Remove the SMTP block:
```python
# REMOVED
SMTP_HOST: Optional[str] = None
SMTP_PORT: int = 587
SMTP_USER: Optional[str] = None
SMTP_PASSWORD: Optional[str] = None
SMTP_FROM: Optional[str] = None
```

Add the Resend block:
```python
# Resend HTTP API (https://resend.com/docs/api-reference/emails/send-email)
# If unset we fall back to console-logged OTPs (local dev without a key).
RESEND_API_KEY: Optional[str] = None
RESEND_FROM: Optional[str] = None   # e.g. "Tazkirati <noreply@yourdomain.com>"
```

Update the corresponding entries in `.env.example` if one exists in the repo (verify during implementation).

### 4.2 Service changes (`backend/src/auth/service.py`)

Delete:
- `import smtplib`
- `from email.mime.multipart import MIMEMultipart`
- `from email.mime.text import MIMEText`

Rewrite `_send_email()`:
```python
import httpx

RESEND_URL = "https://api.resend.com/emails"

def _send_email(to: str, subject: str, html: str, text: str) -> bool:
    """
    Deliver an email via Resend's HTTP API. Returns True on 2xx. On failure
    (or missing config) returns False and the caller falls back to the
    console-log OTP path, keeping local dev workable without a key.
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

The existing functions in the file (`_generate_email_otp`, `register_user`, `verify_email`, `resend_email_otp`, `authenticate`) are not otherwise touched in Part 1. The fallback branch in `_generate_email_otp` (`if not sent: print("[EMAIL-OTP-CONSOLE] …")`) still fires when the key is missing. Part 2 adds new functions to this same file — see §5.2.

### 4.3 Deployment changes

Render dashboard → service → Environment tab:
- **Remove**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- **Add**: `RESEND_API_KEY` (from Resend dashboard), `RESEND_FROM` (verified sender, format `"Tazkirati <noreply@yourdomain.com>"`)

**Sender domain**: Resend requires the sender domain to be verified (DNS SPF/DKIM records). Until verified, Resend only allows sending to the account owner's email. The user will handle domain verification in the Resend dashboard; the implementation is agnostic to it — a wrong/unverified `RESEND_FROM` will just make `_send_email()` return False and the OTP will fall through to the server-log fallback, matching current behavior.

### 4.4 CLAUDE.md updates

- **Known Limitations table**: replace the SMTP-blocked row. New copy:
  > "Resend sender domain must be verified in the Resend dashboard (DNS SPF/DKIM). Until verified, emails only deliver to the account owner's email. No workaround needed once verification completes."
- **Deploy from scratch section**: swap `SMTP_*` env var list for `RESEND_API_KEY` + `RESEND_FROM`.
- **Upgrade path section**: drop the "Outbound SMTP unblocks on Render Starter" bullet — no longer relevant.
- **Add a "Recent fixes" entry** on ship: `Email transport migrated smtplib → Resend HTTP API (unblocks OTP delivery on Render free tier)`.

### 4.5 Tests

- Update any existing test that patched `smtplib` — grep confirms there are none currently, but re-verify during implementation.
- Add a test that stubs `httpx.post` and asserts:
  - Body shape (from/to/subject/html/text)
  - Bearer header
  - Success returns True; non-2xx returns False; exception returns False
- The existing OTP flow tests keep working unchanged — they don't depend on the transport.

## 5. Part 2 — Password reset (backend)

### 5.1 Data model changes

**Zero schema migrations.** The existing `EmailOTP` table already has:
- `email` (str)
- `otp_code` (str)
- `purpose` (str) — currently only used with value `"verify"`
- `expires_at` (datetime)
- `created_at` (datetime)

Add `"reset"` as a second valid value for `purpose`. No constraint change; the column is a free `String`.

### 5.2 New service functions (`backend/src/auth/service.py`)

**`_generate_password_reset_otp(db, email) -> str`** — mirror of `_generate_email_otp` with:
- Same 30s cooldown + 3/hour cap (already keyed on `EmailOTP.email` alone, so it correctly rate-limits across verify AND reset — a spammer flipping between purposes still hits the cap).
- `purpose="reset"` on the created row.
- Different subject line: `"Reset your Tazkirati password"`.
- Different HTML/text copy: "You (or someone using your email) requested a password reset. Enter this 6-digit code to continue: {code}. If you didn't request this, you can safely ignore this email — your password won't change."
- Same pillow-branded HTML template envelope.

**`request_password_reset(db, email) -> None`** — orchestration:
```python
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
```

**`confirm_password_reset(db, email, otp_code, new_password) -> models.User`**:
```python
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

Password validation is enforced at the Pydantic schema layer on `PasswordResetConfirmIn` — see §5.3 for exact constraints (`min_length=6, max_length=128`, matching `RegisterRequest`).

### 5.3 New endpoints (`backend/src/auth/router.py`)

**`POST /auth/password-reset/request`**
- Body: new `PasswordResetRequestIn { email: EmailStr }` schema in `auth/schemas.py`.
- Response: plain dict `{"message": "If an account exists, a reset code has been sent."}` — matches the existing house style in `auth/router.py` for `/register` and `/resend-otp` which return untyped dicts. Same message returned even when nothing was sent.
- Rate limit is enforced inside `_generate_password_reset_otp` (raises 429). We deliberately let that 429 propagate — it's not an account-existence leak because the same rate limit exists on `/auth/resend-otp`; anyone can trigger it against any email.
- HTTP: always 200 on happy path; 429 on rate limit.

**`POST /auth/password-reset/confirm`**
- Body: new `PasswordResetConfirmIn` schema — `email: EmailStr`, `otp_code: str = Field(..., min_length=6, max_length=6)`, `new_password: str = Field(..., min_length=6, max_length=128)`. Password constraints match `RegisterRequest` exactly (verified in `auth/schemas.py`).
- Response: reuse the existing `TokenResponse` schema — returns `{ access_token, token_type: "bearer", user: UserOut }`, auto-signing the user in on successful reset. Mirrors the ergonomics the user expects from the verify-email flow and lands them straight in their home screen without a second sign-in step.
- HTTP: 200 on happy path; 400 on invalid/expired code (same message either way).

Both endpoints registered under the existing `/auth` router prefix.

### 5.4 Tests (`backend/tests/auth/`)

New file `backend/tests/auth/test_password_reset.py`:
1. **Happy path** — request OTP → confirm with valid OTP + new password → returns login token → login with old password fails → login with new password succeeds.
2. **Unknown email silent success** — request with an unregistered email returns 200 with generic message; no `EmailOTP` row created.
3. **Unverified account silent success** — same as above but the user exists and `email_verified=False`.
4. **Wrong OTP** — request valid OTP, confirm with a wrong code, returns 400 "Invalid or expired code".
5. **Expired OTP** — mint OTP, artificially expire it (patch `expires_at`), confirm returns 400.
6. **Cross-purpose OTP rejection** — register a user (creates a `purpose="verify"` OTP), then attempt `password-reset/confirm` with that verify OTP — must return 400 (the `purpose="reset"` filter in the query excludes it).
7. **Rate limit** — two rapid requests within 30s return 429 on the second.
8. **Session token unchanged** — pre-existing JWTs remain valid after a password reset (documents current MVP behavior).

Target: 8 new tests, bringing backend suite from 96 → 104.

## 6. Part 3 — Password reset (frontend, v2/pillow only)

**Hard constraint from CLAUDE.md**: all v2 work lives in `frontend/index-v2.html`; `frontend/index.html` is never touched on this branch. Both new screens are v2-only. v1 users don't get password reset until v2 lands on `main`, which is fine — v1 is preserved as a rollback surface, not an actively supported UX.

### 6.1 Two new screens

**`screen-forgot-password`** (routed from sign-in via new "Forgot password?" link):
- `.p-pillow` container
- One `.p-field` with `.p-input` for email
- Amber `.p-cta`: "Send reset code" (i18n: `auth.forgot.cta`)
- Back link (ghost, top-left in the pillow header): "← Back to sign in"
- On success: toast "Check your email for a reset code" and `goto("reset-password")` with email pre-filled in `STATE.pendingResetEmail`

**`screen-reset-password`** (routed from `forgot-password` or directly from an email deep-link in a future iteration):
- `.p-pillow` container
- Three `.p-field` rows:
  1. 6-digit OTP input (`inputmode="numeric" maxlength="6"`)
  2. New password (`type="password"`)
  3. Confirm new password (`type="password"`)
- Amber `.p-cta`: "Reset password" (i18n: `auth.reset.cta`)
- Client-side mirror check on the two password fields (identical to register screen — reuse the exact same code path if easily factorable, otherwise inline it).
- Resend link with the existing 30s countdown pattern from verify-email (reuse the shared countdown helper if one exists; otherwise mirror the pattern).
- On success: server returns login token + user → `STATE.auth` populated → `paintChrome()` → `goto()` to the appropriate home per role.

### 6.2 Sign-in screen change

Add a "Forgot password?" ghost link directly under the password field on `screen-signin`. Clicking calls `goto("forgot-password")`.

### 6.3 State machine (`goto()` chain in `frontend/index-v2.html`)

Add two new screen ids to the switch/mount code. Both screens follow the existing pattern for auth screens: hide `topbar-nav` (they're pre-authenticated), hide bottom nav.

### 6.4 i18n keys (EN + AR)

Add to the `I18N` table:
```
auth.signin.forgot_link          "Forgot password?"                / "نسيت كلمة المرور؟"
auth.forgot.title                "Reset your password"             / "إعادة تعيين كلمة المرور"
auth.forgot.subtitle             "Enter your email and we'll..."   / "أدخل بريدك الإلكتروني..."
auth.forgot.email_placeholder    "you@example.com"                 / "أنت@مثال.com"
auth.forgot.cta                  "Send reset code"                 / "إرسال رمز الإعادة"
auth.forgot.back                 "← Back to sign in"               / "← العودة إلى تسجيل الدخول"
auth.reset.title                 "Enter your new password"         / "أدخل كلمة المرور الجديدة"
auth.reset.subtitle              "Enter the 6-digit code..."       / "أدخل الرمز المكوّن من 6 أرقام..."
auth.reset.otp_placeholder       "6-digit code"                    / "رمز من 6 أرقام"
auth.reset.new_password          "New password"                    / "كلمة المرور الجديدة"
auth.reset.confirm_password      "Confirm new password"            / "تأكيد كلمة المرور الجديدة"
auth.reset.cta                   "Reset password"                  / "إعادة تعيين كلمة المرور"
toast.forgot.sent                "Check your email for a code"     / "تحقّق من بريدك للحصول على الرمز"
toast.reset.success              "Password reset — you're signed in" / "تم إعادة التعيين — لقد تم تسجيل دخولك"
toast.reset.mismatch             "Passwords don't match"           / "كلمات المرور غير متطابقة"
toast.reset.invalid_code         "Invalid or expired code"         / "رمز غير صالح أو منتهي الصلاحية"
```

15 keys total. Arabic wording is a first pass — the user can polish during implementation.

### 6.5 API layer

Two new methods on the existing `api()` wrapper convention (matches `api(path, {method, body: JSON.stringify(...)})` — see the commission-modal fix in "Recent fixes" for the correct signature):

```js
// Request a reset code
await api('/auth/password-reset/request', { method: 'POST', body: JSON.stringify({ email }) });

// Confirm the reset
const { access_token, user } = await api('/auth/password-reset/confirm', {
  method: 'POST',
  body: JSON.stringify({ email, otp_code, new_password }),
});
```

### 6.6 Cross-cutting

- **RTL**: numeric OTP input forces `direction: ltr` in Arabic mode (same treatment as verify-email OTP input — see the existing pattern).
- **`tazStore`**: same auto-persist of `STATE.auth` on the native shell after successful reset.
- **Cold-start toast**: the shared `toast.waking_server` machinery will fire on the reset request if the Render service is cold — no special handling needed.

## 7. Rollout & rollback

**Rollout**:
1. Merge to `redesign/pillow` (or successor branch).
2. Set `RESEND_API_KEY` + `RESEND_FROM` on Render before the deploy.
3. On deploy, verify email delivery by triggering a fresh registration on the demo customer email.
4. Verify password reset end-to-end on the same account.

**Rollback**:
- **Transport-level**: unset `RESEND_API_KEY` in Render env → `_send_email()` returns False → OTPs fall back to console log (users blocked from verifying, but the app doesn't crash). This is a clean escape hatch if Resend is misconfigured.
- **Code-level**: revert the merge commit. The old SMTP code is preserved in git history.
- **Password-reset regression**: the two endpoints are new; reverting them doesn't affect any existing user flow. `EmailOTP` rows with `purpose="reset"` are harmless leftovers (verify-email query filters on `purpose="verify"` so they're ignored, and the reaper isn't involved in this table).

## 8. Open questions for the implementation plan

- Does `SecretStr` from `pydantic_settings` make sense for `RESEND_API_KEY`? (Nice-to-have — prevents accidental logging. Check the existing `SECRET_KEY` handling in `config.py` for house style.)
- Reuse or fork the pillow HTML email template? Recommend factoring into a small `_render_otp_email(code, purpose)` helper that returns `(subject, html, text)` and internally branches on purpose. Keeps both emails visually identical.
- Verify the register screen's password + confirm-password mirror check is a shared helper before duplicating it on the reset screen. If not, factor it out during this work.

Answers to these get resolved in the implementation plan (writing-plans skill next).
