"""ADMIN-2 per-provider capability toggles.

Covers:
  - Default flags on newly-created providers are all True.
  - GET /admin/providers exposes the flags.
  - PATCH /admin/providers/{id}/capabilities does a partial update.
  - When can_add_trips is False, POST /trips returns 403 with a helpful msg.
  - When can_delete_trips is False, DELETE /trips/{id} returns 403.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password
from src.inventory.models import Route, Bus, Trip


@pytest.fixture
def provider(db):
    """A working active provider. Trip add + delete both allowed by default."""
    u = User(
        email="p1@x.com", full_name="Provider One",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def provider_auth(client, provider):
    r = client.post("/auth/login", json={"email": provider.email, "password": "Test#2026"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_defaults_are_true(provider):
    assert provider.can_add_trips is True
    assert provider.can_edit_trips is True
    assert provider.can_delete_trips is True


def test_list_providers_exposes_flags(client, auth_header, provider):
    r = client.get("/admin/providers", headers=auth_header)
    assert r.status_code == 200, r.text
    rows = [p for p in r.json() if p["id"] == provider.id]
    assert rows and rows[0]["can_add_trips"] is True
    assert rows[0]["can_edit_trips"] is True
    assert rows[0]["can_delete_trips"] is True


def test_patch_partial_update(client, auth_header, provider):
    r = client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_add_trips": False},  # only touch add; other two stay
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_add_trips"] is False
    assert body["can_edit_trips"] is True
    assert body["can_delete_trips"] is True


def test_patch_all_three(client, auth_header, provider):
    r = client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_add_trips": False, "can_edit_trips": False, "can_delete_trips": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert not (body["can_add_trips"] or body["can_edit_trips"] or body["can_delete_trips"])


def test_create_trip_blocked_when_add_disabled(
    client, auth_header, provider, provider_auth, db,
):
    # Admin disables add
    client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_add_trips": False},
    )
    # Provider attempts to create a trip → 403
    r = client.post(
        "/trips",
        headers=provider_auth,
        json={
            "origin": "Khartoum",
            "destination": "Port Sudan",
            "departure_time": "2030-01-01T09:00:00Z",
            "total_seats": 45,
            "price": 8,
            "repeat": {"kind": "once"},
        },
    )
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_delete_trip_blocked_when_delete_disabled(
    client, auth_header, provider, provider_auth, db,
):
    # Seed a trip the provider owns
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus])
    db.flush()
    from datetime import datetime, timedelta
    trip = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=1), price=8,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)

    # Admin disables delete
    client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_delete_trips": False},
    )

    # Provider attempts to delete → 403
    r = client.delete(f"/trips/{trip.id}", headers=provider_auth)
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"].lower()


def test_admin_delete_still_works_when_provider_delete_disabled(
    client, auth_header, provider, db,
):
    """Admin's /admin/trips/{id} DELETE bypasses the provider capability
    flag — that flag only gates the provider's own /trips/{id}."""
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus])
    db.flush()
    from datetime import datetime, timedelta
    trip = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=1), price=8,
    )
    db.add(trip)
    db.commit()
    trip_id = trip.id

    client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_delete_trips": False},
    )
    r = client.delete(f"/admin/trips/{trip_id}", headers=auth_header)
    assert r.status_code == 204
