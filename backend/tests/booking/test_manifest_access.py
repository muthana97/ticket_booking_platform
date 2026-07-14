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
