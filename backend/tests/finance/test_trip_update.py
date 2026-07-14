"""GEN-2 / Task #4 — trip edit endpoint.

Covers:
  - Provider PATCH updates price + departure on their own trip.
  - can_edit_trips=False → 403 on provider PATCH.
  - Cross-provider PATCH → 403.
  - Past-departure PATCH → 400.
  - Existing booking's total_price is NOT retroactively adjusted.
  - Admin PATCH works regardless of ownership or capability flag.
"""
from datetime import datetime, timedelta

import pytest

from src.auth.models import User
from src.auth.utils import hash_password
from src.inventory.models import Route, Bus, Trip, Seat
from src.booking.models import Booking


@pytest.fixture
def provider(db):
    u = User(
        email="p1@x.com", full_name="Provider One",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def other_provider(db):
    u = User(
        email="p2@x.com", full_name="Provider Two",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def provider_auth(client, provider):
    r = client.post("/auth/login", json={"email": provider.email, "password": "Test#2026"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def trip(db, provider):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=7), price=8,
    )
    db.add(t); db.commit(); db.refresh(t); return t


def test_provider_can_update_own_trip(client, provider_auth, trip):
    new_time = (datetime.utcnow() + timedelta(days=10)).replace(microsecond=0)
    r = client.patch(
        f"/trips/{trip.id}", headers=provider_auth,
        json={"price": 12, "departure_time": new_time.isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price"] == 12
    assert body["departure_time"].startswith(new_time.isoformat().split("T")[0])


def test_price_only_partial_update(client, provider_auth, trip):
    original_dep = trip.departure_time.isoformat()
    r = client.patch(f"/trips/{trip.id}", headers=provider_auth, json={"price": 15})
    assert r.status_code == 200
    assert r.json()["price"] == 15
    # departure untouched
    assert r.json()["departure_time"].startswith(original_dep.split("T")[0])


def test_past_departure_rejected(client, provider_auth, trip):
    past = (datetime.utcnow() - timedelta(hours=1)).replace(microsecond=0)
    r = client.patch(
        f"/trips/{trip.id}", headers=provider_auth,
        json={"departure_time": past.isoformat()},
    )
    assert r.status_code == 400
    assert "past" in r.json()["detail"].lower()


def test_cross_provider_edit_forbidden(client, db, provider, other_provider, trip):
    r = client.post(
        "/auth/login",
        json={"email": other_provider.email, "password": "Test#2026"},
    )
    other_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.patch(f"/trips/{trip.id}", headers=other_auth, json={"price": 20})
    assert r.status_code == 403
    assert "own" in r.json()["detail"].lower()


def test_edit_blocked_by_capability_flag(client, auth_header, provider_auth, provider, trip):
    client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header, json={"can_edit_trips": False},
    )
    r = client.patch(f"/trips/{trip.id}", headers=provider_auth, json={"price": 25})
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_existing_booking_price_not_retroactive(client, db, provider_auth, trip):
    # Seed a booking at the original price
    for name in ("1A", "1B"):
        db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))
    db.commit()
    from src.booking.service import lock_seats
    from types import SimpleNamespace
    lock_seats(
        db, trip_id=trip.id, seat_numbers=["1A"],
        customer_id=1, total_price=8,
        passengers=[SimpleNamespace(full_name="Mohamed Ali", phone_number=None,
                                    national_id=None, seat_number="1A")],
    )
    # Provider bumps price to 30 — should NOT touch the locked booking
    r = client.patch(f"/trips/{trip.id}", headers=provider_auth, json={"price": 30})
    assert r.status_code == 200
    booking = db.query(Booking).filter(Booking.trip_id == trip.id).first()
    assert booking.total_price == 8, "existing bookings must keep their locked price"


def test_admin_can_update_any_trip(client, auth_header, trip):
    r = client.patch(f"/admin/trips/{trip.id}", headers=auth_header, json={"price": 42})
    assert r.status_code == 200, r.text
    assert r.json()["price"] == 42


def test_admin_bypasses_capability_flag(client, auth_header, provider, trip):
    client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header, json={"can_edit_trips": False},
    )
    r = client.patch(f"/admin/trips/{trip.id}", headers=auth_header, json={"price": 50})
    assert r.status_code == 200
    assert r.json()["price"] == 50
