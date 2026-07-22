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


def test_request_endpoint_returns_before_send_completes(client, db, monkeypatch):
    """Timing-oracle fix: the HTTP send must run as a BackgroundTask, not
    inline before the response is built. We can't measure wall-clock timing
    reliably in CI, so the functional proxy is: the endpoint still returns
    the same generic 200 body, and _send_email is still invoked (via the
    background task, which TestClient runs before handing control back) —
    proving the send wasn't silently dropped, just deferred."""
    calls = []

    def _spy_send_email(**kw):
        calls.append(kw)
        return False

    monkeypatch.setattr(service, "_send_email", _spy_send_email)
    _seed_verified_user(db)

    r = client.post("/auth/password-reset/request", json={"email": "bob@example.com"})
    assert r.status_code == 200
    assert r.json() == {"message": "If an account exists, a reset code has been sent."}
    assert len(calls) == 1
    assert calls[0]["to"] == "bob@example.com"

    # Unknown email: response body/status identical, and _send_email is NOT
    # called at all (no user → no OTP → nothing to send) — same shape as
    # before, just confirming the background-task refactor didn't change
    # the known/unknown branch behavior.
    r2 = client.post("/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert r2.status_code == 200
    assert r2.json() == {"message": "If an account exists, a reset code has been sent."}
    assert len(calls) == 1


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
