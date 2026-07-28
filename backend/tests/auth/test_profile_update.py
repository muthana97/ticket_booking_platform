"""PATCH /auth/me — self-service profile edits.

Six scenarios: full replace, partial patch (name only), clearing nullable
fields with explicit null, no-op empty payload, min-length rejection at
the schema layer, and auth-required guard.
"""
from src.auth import models, utils


def _seed_customer(db, email="alice@example.com", password="Pass#2026"):
    user = models.User(
        email=email,
        password_hash=utils.hash_password(password),
        full_name="Alice Old",
        phone_number="+249000000000",
        national_id="OLD-ID",
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login_headers(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_patch_me_updates_all_fields(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch(
        "/auth/me",
        headers=headers,
        json={
            "full_name": "Alice New",
            "phone_number": "+249111111111",
            "national_id": "NEW-ID",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice New"
    assert body["phone_number"] == "+249111111111"
    assert body["national_id"] == "NEW-ID"

    # Persisted to DB
    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.full_name == "Alice New"
    assert row.phone_number == "+249111111111"
    assert row.national_id == "NEW-ID"


def test_patch_me_partial_updates_only_name(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "Alice Renamed"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice Renamed"
    assert body["phone_number"] == "+249000000000"
    assert body["national_id"] == "OLD-ID"


def test_patch_me_clears_phone_and_id_with_null(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch(
        "/auth/me",
        headers=headers,
        json={"phone_number": None, "national_id": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone_number"] is None
    assert body["national_id"] is None

    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.phone_number is None
    assert row.national_id is None
    # Name unchanged
    assert row.full_name == "Alice Old"


def test_patch_me_empty_payload_is_noop(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice Old"
    assert body["phone_number"] == "+249000000000"
    assert body["national_id"] == "OLD-ID"


def test_patch_me_rejects_short_name(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "A"})
    assert r.status_code == 422

    # Nothing persisted
    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.full_name == "Alice Old"


def test_patch_me_requires_auth(client, db):
    _seed_customer(db)
    r = client.patch("/auth/me", json={"full_name": "Whoever"})
    assert r.status_code == 401
