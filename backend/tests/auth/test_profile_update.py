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


def test_patch_me_works_for_provider(client, db):
    """PATCH /auth/me is role-agnostic — provider can self-edit."""
    user = models.User(
        email="op@example.com",
        password_hash=utils.hash_password("Op#2026-A"),
        full_name="Op Original",
        role="provider",
        status="active",
        email_verified=True,
    )
    db.add(user); db.commit(); db.refresh(user)
    headers = _login_headers(client, "op@example.com", "Op#2026-A")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "Op Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Op Renamed"


def test_patch_me_works_for_admin(client, db):
    """PATCH /auth/me is role-agnostic — admin can self-edit."""
    user = models.User(
        email="a@example.com",
        password_hash=utils.hash_password("Adm#2026-A"),
        full_name="Adm Original",
        role="admin",
        status="active",
        email_verified=True,
    )
    db.add(user); db.commit(); db.refresh(user)
    headers = _login_headers(client, "a@example.com", "Adm#2026-A")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "Adm Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Adm Renamed"


def test_patch_me_ignores_unknown_fields(client, db):
    """Pydantic v2 default is extra='ignore'. Ensures no privilege-escalation
    or identity-change vector via a rogue payload."""
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch(
        "/auth/me",
        headers=headers,
        json={
            "full_name": "Alice New",
            "email": "hijack@example.com",
            "role": "admin",
            "status": "blocked",
            "id": 999999,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"  # unchanged
    assert body["role"] == "customer"            # unchanged
    assert body["status"] == "active"            # unchanged
    assert body["full_name"] == "Alice New"      # only known field applied


def test_patch_me_does_not_touch_existing_booking_passengers(client, db):
    """CLAUDE.md invariant: profile edits are forward-only. Existing bookings
    snapshot passenger data at seat-lock time — a rename after the fact must
    not rewrite the passenger row on any existing booking."""
    from datetime import datetime, timedelta

    from src.inventory.models import Route, Bus, Trip
    from src.booking.models import Booking, Passenger

    # Seed a customer whose name we'll change.
    customer = models.User(
        email="alice@example.com",
        password_hash=utils.hash_password("Pass#2026"),
        full_name="Alice Original",
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(customer)

    # Minimal seeded provider + route + bus + trip to hang a booking off.
    provider = models.User(
        email="op@example.com",
        password_hash=utils.hash_password("Op#2026-A"),
        full_name="Op",
        role="provider",
        status="active",
        email_verified=True,
    )
    db.add(provider); db.commit(); db.refresh(provider); db.refresh(customer)

    route = Route(origin="Khartoum", destination="Port Sudan", duration="10h")
    bus = Bus(provider_id=provider.id, name="Bus 1", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()

    trip = Trip(
        provider_id=provider.id,
        bus_id=bus.id,
        route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=3),
        price=100,
    )
    db.add(trip); db.commit(); db.refresh(trip)

    booking = Booking(
        customer_id=customer.id,
        trip_id=trip.id,
        status="confirmed",
        total_price=100,
        channel="consumer",
    )
    db.add(booking); db.commit(); db.refresh(booking)

    pax = Passenger(
        booking_id=booking.id,
        seat_number="1A",
        full_name="Alice Original",
        phone_number=None,
        national_id=None,
    )
    db.add(pax); db.commit(); db.refresh(pax)
    original_pax_id = pax.id

    # Rename the customer via PATCH /auth/me.
    headers = _login_headers(client, "alice@example.com", "Pass#2026")
    r = client.patch("/auth/me", headers=headers, json={"full_name": "Alice Renamed"})
    assert r.status_code == 200, r.text

    # Passenger row on the existing booking is untouched.
    db.expire_all()
    pax_after = db.query(Passenger).filter_by(id=original_pax_id).one()
    assert pax_after.full_name == "Alice Original"
    assert pax_after.booking_id == booking.id
