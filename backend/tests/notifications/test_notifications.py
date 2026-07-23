"""Task #5 — notifications subsystem.

Covers:
  - GET /notifications/me returns unread count + items.
  - POST /notifications/{id}/read marks a single one read.
  - POST /notifications/read-all zeroes the unread count.
  - Trip-time edit fans out to consumer-booking customers only (walk-in
    self-notifies are skipped).
  - Provider edit → admin notified. Admin edit → provider notified.
  - Provider capability toggle → provider notified per changed field.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.auth.models import User
from src.auth.utils import hash_password
from src.inventory.models import Route, Bus, Trip, Seat
from src.booking.service import lock_seats


def _pax(name, seat):
    return SimpleNamespace(full_name=name, phone_number=None, national_id=None, seat_number=seat)


@pytest.fixture
def provider(db):
    u = User(
        email="p1@x.com", full_name="Provider One",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def customer(db):
    u = User(
        email="cust@x.com", full_name="Cust One",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def customer_auth(client, customer):
    r = client.post("/auth/login", json={"email": customer.email, "password": "Test#2026"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def provider_auth(client, provider):
    r = client.post("/auth/login", json={"email": provider.email, "password": "Test#2026"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def trip_with_seats(db, provider):
    route = Route(origin="K", destination="P", duration="4h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=5), price=8,
    )
    db.add(t); db.flush()
    for name in ("1A", "1B", "2A"):
        db.add(Seat(trip_id=t.id, seat_number=name, status="available"))
    db.commit(); db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# Endpoint smoke
# ---------------------------------------------------------------------------

def test_list_empty(client, customer_auth):
    r = client.get("/notifications/me", headers=customer_auth)
    assert r.status_code == 200
    body = r.json()
    assert body == {"unread": 0, "items": []}


def test_create_and_read_one(client, customer_auth, customer, db):
    from src.notifications.service import create_notification
    n = create_notification(db, user_id=customer.id, type="test", payload={"x": 1})
    r = client.get("/notifications/me", headers=customer_auth)
    body = r.json()
    assert body["unread"] == 1 and len(body["items"]) == 1
    r = client.post(f"/notifications/{n.id}/read", headers=customer_auth)
    assert r.status_code == 200
    r = client.get("/notifications/me", headers=customer_auth)
    assert r.json()["unread"] == 0


def test_read_all(client, customer_auth, customer, db):
    from src.notifications.service import create_notification
    for i in range(3):
        create_notification(db, user_id=customer.id, type="test", payload={"i": i})
    r = client.post("/notifications/read-all", headers=customer_auth)
    assert r.json()["marked"] == 3
    r = client.get("/notifications/me", headers=customer_auth)
    assert r.json()["unread"] == 0


def test_cannot_read_someone_elses(client, customer_auth, provider, db):
    from src.notifications.service import create_notification
    n = create_notification(db, user_id=provider.id, type="test", payload={})
    r = client.post(f"/notifications/{n.id}/read", headers=customer_auth)
    assert r.status_code == 404  # customer can't see the provider's notification


# ---------------------------------------------------------------------------
# Fan-out on trip edits
# ---------------------------------------------------------------------------

def test_provider_time_edit_notifies_passenger(
    client, provider_auth, customer, trip_with_seats, db,
):
    # Customer books a seat via the service (skips the /bookings/lock HTTP path
    # since we already trust it).
    lock_seats(
        db, trip_id=trip_with_seats.id, seat_numbers=["1A"],
        customer_id=customer.id, total_price=8,
        passengers=[_pax("Mohamed Ali", "1A")], channel="consumer",
        actor_user_id=customer.id,
    )
    new_time = (datetime.utcnow() + timedelta(days=10)).replace(microsecond=0)
    r = client.patch(
        f"/trips/{trip_with_seats.id}", headers=provider_auth,
        json={"departure_time": new_time.isoformat()},
    )
    assert r.status_code == 200
    # Customer should have one trip_time_changed notification
    from src.notifications.models import Notification
    rows = db.query(Notification).filter(
        Notification.user_id == customer.id,
        Notification.type == "trip_time_changed",
    ).all()
    assert len(rows) == 1
    assert rows[0].payload["trip_id"] == trip_with_seats.id
    assert "from" in rows[0].payload and "to" in rows[0].payload


def test_price_edit_does_not_notify_passengers(
    client, provider_auth, customer, trip_with_seats, db,
):
    """Price change is silent for passengers — their locked-in price is
    unchanged, so no reason to bother them."""
    lock_seats(
        db, trip_id=trip_with_seats.id, seat_numbers=["1A"],
        customer_id=customer.id, total_price=8,
        passengers=[_pax("Mohamed Ali", "1A")], channel="consumer",
        actor_user_id=customer.id,
    )
    r = client.patch(f"/trips/{trip_with_seats.id}", headers=provider_auth, json={"price": 20})
    assert r.status_code == 200
    from src.notifications.models import Notification
    passenger_rows = db.query(Notification).filter(Notification.user_id == customer.id).all()
    assert not passenger_rows


def test_provider_edit_notifies_admin(
    client, provider_auth, admin_user, trip_with_seats, db,
):
    r = client.patch(f"/trips/{trip_with_seats.id}", headers=provider_auth, json={"price": 25})
    assert r.status_code == 200
    from src.notifications.models import Notification
    rows = db.query(Notification).filter(
        Notification.user_id == admin_user.id,
        Notification.type == "trip_edited_by_provider",
    ).all()
    assert len(rows) == 1
    assert rows[0].payload["trip_id"] == trip_with_seats.id
    assert "price" in rows[0].payload
    # New attribution: payload carries the acting provider's full name.
    assert rows[0].payload["provider_name"] == "Provider One"


def test_historical_notifs_backfilled_with_provider_name(
    client, auth_header, admin_user, provider, trip_with_seats, db,
):
    """Regression: notifications written before the provider_name field
    existed only carried provider_id. GET /notifications/me must enrich
    them at read time so the admin console can show the name."""
    from src.notifications.models import Notification
    # Simulate a pre-fix notification — payload has provider_id but no name.
    legacy = Notification(
        user_id=admin_user.id,
        type="trip_edited_by_provider",
        payload={"trip_id": trip_with_seats.id, "provider_id": provider.id,
                 "changed_fields": ["price"]},
        created_at=datetime.utcnow(),
    )
    db.add(legacy); db.commit()
    legacy_id = legacy.id

    r = client.get("/notifications/me", headers=auth_header)
    assert r.status_code == 200
    items = r.json()["items"]
    match = next(i for i in items if i["id"] == legacy_id)
    assert match["payload"]["provider_name"] == "Provider One"


def test_admin_edit_notifies_owning_provider(
    client, auth_header, provider, trip_with_seats, db,
):
    r = client.patch(f"/admin/trips/{trip_with_seats.id}", headers=auth_header, json={"price": 42})
    assert r.status_code == 200
    from src.notifications.models import Notification
    rows = db.query(Notification).filter(
        Notification.user_id == provider.id,
        Notification.type == "trip_edited_by_admin",
    ).all()
    assert len(rows) == 1


def test_capability_toggle_notifies_provider(
    client, auth_header, provider, db,
):
    r = client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_add_trips": False},
    )
    assert r.status_code == 200
    from src.notifications.models import Notification
    rows = db.query(Notification).filter(
        Notification.user_id == provider.id,
        Notification.type == "provider_capability_changed",
    ).all()
    assert len(rows) == 1
    assert rows[0].payload == {"capability": "can_add_trips", "value": False}
