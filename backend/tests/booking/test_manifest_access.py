"""Task #6 — manifest endpoint access rules.

  - admin           → any trip (200)
  - owning provider → own trip (200)
  - other provider  → 403
  - customer        → 403
"""
from datetime import datetime, timedelta

import pytest

from src.auth.models import User
from src.auth.utils import hash_password
from src.inventory.models import Route, Bus, Trip


@pytest.fixture
def owning_provider(db):
    u = User(
        email="own@x.com", full_name="Owner",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def other_provider(db):
    u = User(
        email="other@x.com", full_name="Other",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def customer(db):
    u = User(
        email="cust@x.com", full_name="Cust",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def trip(db, owning_provider):
    route = Route(origin="K", destination="P", duration="4h")
    bus = Bus(provider_id=owning_provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=owning_provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=1), price=8,
    )
    db.add(t); db.commit(); db.refresh(t); return t


def _auth_for(client, user):
    r = client.post("/auth/login", json={"email": user.email, "password": "Test#2026"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_admin_ok(client, auth_header, trip):
    r = client.get(f"/bookings/trips/{trip.id}/manifest", headers=auth_header)
    assert r.status_code == 200


def test_owning_provider_ok(client, owning_provider, trip):
    r = client.get(f"/bookings/trips/{trip.id}/manifest", headers=_auth_for(client, owning_provider))
    assert r.status_code == 200


def test_other_provider_forbidden(client, other_provider, trip):
    r = client.get(f"/bookings/trips/{trip.id}/manifest", headers=_auth_for(client, other_provider))
    assert r.status_code == 403


def test_customer_forbidden(client, customer, trip):
    r = client.get(f"/bookings/trips/{trip.id}/manifest", headers=_auth_for(client, customer))
    assert r.status_code == 403


def test_manifest_ok_when_passenger_phone_is_null(client, auth_header, db, trip):
    """Regression: phone_number became nullable in GEN-1, so the manifest
    response schema must not require it. Reproduces the Trip #9 admin 500."""
    from src.inventory.models import Seat
    from src.booking.models import Booking, Passenger
    seat = Seat(trip_id=trip.id, seat_number="1A", status="booked")
    db.add(seat); db.flush()
    booking = Booking(
        trip_id=trip.id, customer_id=1, total_price=trip.price,
        status="confirmed", channel="walkin",
    )
    db.add(booking); db.flush()
    db.add(Passenger(
        booking_id=booking.id, full_name="No Phone Guy",
        seat_number="1A", phone_number=None, national_id=None,
    ))
    db.commit()

    r = client.get(f"/bookings/trips/{trip.id}/manifest", headers=auth_header)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_confirmed_passengers"] == 1
    assert body["manifest"][0]["phone_number"] is None
