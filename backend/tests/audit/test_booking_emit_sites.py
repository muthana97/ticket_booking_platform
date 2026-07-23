"""Task 4 — audit emits from the booking flow:
  - consumer_booked   (POST /bookings/lock)
  - walkin_booked     (POST /bookings/walkin)
  - billing_ref_generated (POST /bookings/intent/billing)
  - cash_confirmed    (POST /bookings/{id}/provider-confirm — branches the
                        shared admin.service.confirm_payment emit)
"""
from datetime import datetime, timedelta

from src.audit import models as audit_models
from src.auth import models as auth_models
from src.auth.utils import hash_password
from src.inventory.models import Bus, Route, Seat, Trip


def _login_as(client, email, password="pw"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db, role, status, email):
    u = auth_models.User(
        email=email, password_hash=hash_password("pw"), full_name=f"{role.title()} {email}",
        role=role, status=status, email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _seed_trip(db, provider, seats=("1A", "1B", "1C")):
    route = Route(origin="Cairo", destination="Aswan", duration="10h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    trip = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=2),
        price=100.0,
    )
    db.add(trip); db.flush()
    for name in seats:
        db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))
    db.commit()
    db.refresh(trip)
    return trip


def test_consumer_lock_emits_consumer_booked(client, db):
    provider = _seed(db, "provider", "active", "prov1@x.com")
    customer = _seed(db, "customer", "active", "cust1@x.com")
    trip = _seed_trip(db, provider)

    h = _login_as(client, customer.email)
    r = client.post("/bookings/lock", headers=h, json={
        "trip_id": trip.id,
        "seat_numbers": ["1A"],
        "total_price": 100.0,
        "passengers": [],
    })
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]

    row = db.query(audit_models.AuditEvent).filter_by(event_type="consumer_booked").one()
    assert row.actor_user_id == customer.id
    assert row.provider_id == trip.provider_id
    assert row.target_type == "booking"
    assert row.target_id == booking_id
    assert customer.full_name in row.summary
    assert f"trip #{trip.id}" in row.summary


def test_walkin_lock_emits_walkin_booked(client, db):
    provider = _seed(db, "provider", "active", "prov2@x.com")
    trip = _seed_trip(db, provider)

    h = _login_as(client, provider.email)
    r = client.post("/bookings/walkin", headers=h, json={
        "trip_id": trip.id,
        "seat_numbers": ["1A", "1B"],
        "total_price": 200.0,
        "passengers": [],
    })
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]

    row = db.query(audit_models.AuditEvent).filter_by(event_type="walkin_booked").one()
    assert row.actor_user_id == provider.id
    assert row.provider_id == provider.id
    assert row.target_type == "booking"
    assert row.target_id == booking_id
    assert provider.full_name in row.summary
    assert "walk-in" in row.summary.lower()


def test_billing_intent_emits_billing_ref_generated(client, db):
    provider = _seed(db, "provider", "active", "prov3@x.com")
    customer = _seed(db, "customer", "active", "cust3@x.com")
    trip = _seed_trip(db, provider)

    h = _login_as(client, customer.email)
    r = client.post("/bookings/lock", headers=h, json={
        "trip_id": trip.id,
        "seat_numbers": ["1A"],
        "total_price": 100.0,
        "passengers": [],
    })
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]

    r2 = client.post("/bookings/intent/billing", headers=h, json={"booking_id": booking_id})
    assert r2.status_code == 200, r2.text
    billing_ref = r2.json()["billing_reference"]

    row = db.query(audit_models.AuditEvent).filter_by(event_type="billing_ref_generated").one()
    assert row.actor_user_id == customer.id
    assert row.provider_id == trip.provider_id
    assert row.target_type == "booking"
    assert row.target_id == booking_id
    assert billing_ref in row.summary
    assert f"#{booking_id}" in row.summary


def test_provider_confirm_cash_emits_cash_confirmed(client, db):
    """Walk-in cash confirm must branch the SHARED admin.service.confirm_payment
    emit to 'cash_confirmed' — NOT the admin manual-confirm 'payment_confirmed'."""
    provider = _seed(db, "provider", "active", "prov4@x.com")
    trip = _seed_trip(db, provider)

    h = _login_as(client, provider.email)
    r = client.post("/bookings/walkin", headers=h, json={
        "trip_id": trip.id,
        "seat_numbers": ["1A"],
        "total_price": 100.0,
        "passengers": [],
    })
    assert r.status_code == 200, r.text
    booking_id = r.json()["booking_id"]

    r2 = client.post(f"/bookings/{booking_id}/provider-confirm", headers=h)
    assert r2.status_code == 200, r2.text

    # Exactly one payment-side emit, and it must be cash_confirmed.
    rows = db.query(audit_models.AuditEvent).filter(
        audit_models.AuditEvent.event_type.in_(["cash_confirmed", "payment_confirmed"])
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "cash_confirmed"
    assert row.actor_user_id == provider.id
    assert row.provider_id == trip.provider_id
    assert row.target_type == "booking"
    assert row.target_id == booking_id
    assert "cash" in row.summary.lower()
