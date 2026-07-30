"""Care admin role acceptance + endpoint-gating tests.

Covers require_admin_or_care in isolation, then walks every admin
endpoint asserting the correct 200/403 for a care admin logged in.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password


# ----- fixtures -----

@pytest.fixture
def care_admin(db):
    """A care admin account. Active, email-verified, minted directly."""
    u = User(
        email="care@tazkirati.app", full_name="Care Agent",
        password_hash=hash_password("Test#2026"),
        role="care_admin", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def care_auth(client, care_admin):
    r = client.post("/auth/login", json={
        "email": care_admin.email, "password": "Test#2026",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def blocked_care_admin(db):
    u = User(
        email="care-blocked@tazkirati.app", full_name="Blocked Agent",
        password_hash=hash_password("Test#2026"),
        role="care_admin", status="blocked", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


# ----- dependency-level tests -----

def test_require_admin_or_care_accepts_admin(client, auth_header):
    """Full admin passes require_admin_or_care — verified by hitting any
    endpoint that uses it (list bookings is one)."""
    r = client.get("/admin/bookings", headers=auth_header)
    assert r.status_code == 200, r.text


def test_require_admin_or_care_accepts_care_admin(client, care_auth):
    r = client.get("/admin/bookings", headers=care_auth)
    assert r.status_code == 200, r.text


def test_require_admin_or_care_rejects_customer(client, db):
    from src.auth.models import User
    u = User(
        email="cust@x.com", full_name="Cust Omer",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit()
    r = client.post("/auth/login", json={"email": u.email, "password": "Test#2026"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/admin/bookings", headers=headers)
    assert r.status_code == 403


def test_require_admin_or_care_rejects_provider(client, provider_user):
    r = client.post("/auth/login", json={
        "email": provider_user.email, "password": "Test#2026",
    })
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/admin/bookings", headers=headers)
    assert r.status_code == 403


def test_require_admin_or_care_rejects_blocked_care(client, blocked_care_admin):
    r = client.post("/auth/login", json={
        "email": blocked_care_admin.email, "password": "Test#2026",
    })
    # Login should succeed OR fail — either way subsequent /admin call is 403.
    # If login succeeds, get_current_user raises 403 for status=blocked.
    if r.status_code == 200:
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = client.get("/admin/bookings", headers=headers)
        assert r2.status_code == 403
    else:
        assert r.status_code == 403


def test_require_admin_or_care_rejects_unauth(client):
    r = client.get("/admin/bookings")
    assert r.status_code == 401


# ----- endpoint gating: care admin CAN reach these -----

def test_care_admin_can_view_providers(client, care_auth):
    r = client.get("/admin/providers", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_trips(client, care_auth):
    r = client.get("/admin/trips", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_bookings(client, care_auth):
    r = client.get("/admin/bookings", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_pending_payments(client, care_auth):
    r = client.get("/admin/payments/pending", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_provider_log(client, care_auth, provider_user):
    r = client.get(f"/admin/providers/{provider_user.id}/log", headers=care_auth)
    assert r.status_code == 200, r.text


# ----- endpoint gating: care admin CANNOT reach these -----

def test_care_admin_cannot_approve_provider(client, care_auth, provider_user):
    r = client.post(f"/admin/providers/{provider_user.id}/approve", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_block_provider(client, care_auth, provider_user):
    r = client.post(f"/admin/providers/{provider_user.id}/block", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_toggle_capabilities(client, care_auth, provider_user):
    r = client.patch(
        f"/admin/providers/{provider_user.id}/capabilities",
        headers=care_auth, json={"can_add_trips": False},
    )
    assert r.status_code == 403


def test_care_admin_cannot_edit_trip(client, care_auth):
    # Any trip id will do — the auth gate fires before the row lookup.
    r = client.patch("/admin/trips/1", headers=care_auth, json={"price": 999})
    assert r.status_code == 403


def test_care_admin_cannot_delete_trip(client, care_auth):
    r = client.delete("/admin/trips/1", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_view_aggregate_reports(client, care_auth):
    r = client.get("/admin/reports", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_view_provider_reports_drilldown(client, care_auth, provider_user):
    r = client.get(f"/admin/providers/{provider_user.id}/reports", headers=care_auth)
    assert r.status_code == 403


# ----- payment confirm (the one care admin mutation) -----

def test_care_admin_can_confirm_payment(client, care_auth, db):
    """Care admin can confirm a pending payment. Uses a seeded booking that
    has bill_generated_at set (Path B billing intent) so it's confirmable.

    NOTE (adjusted from the brief per task-1-brief.md's own escape hatch):
    the real `Trip` model (backend/src/inventory/models.py) has no
    `origin`/`destination`/`seat_layout` columns — those live on `Route`
    and are joined via `Trip.route_id` (nullable). Dropped them from the
    Trip() call below; route_id stays None which is fine since no
    CommissionRule rows exist in this test DB (commission resolves to 0).
    Also fixed `Booking.billing_ref` -> `Booking.billing_reference` to
    match the actual column name.
    """
    from src.auth.models import User
    from src.inventory.models import Trip
    from src.booking.models import Booking
    from datetime import datetime, timezone, timedelta

    # A provider + trip + committed_pending booking with a billing ref.
    prov = User(
        email="pconfirm@x.com", full_name="Pay Provider",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(prov); db.commit(); db.refresh(prov)
    trip = Trip(
        provider_id=prov.id,
        departure_time=datetime.now(timezone.utc) + timedelta(days=3),
        price=100,
    )
    db.add(trip); db.commit(); db.refresh(trip)
    booking = Booking(
        trip_id=trip.id, status="committed_pending",
        total_price=100, channel="consumer",
        billing_reference="BOK-TEST-01",
        bill_generated_at=datetime.now(timezone.utc),
    )
    db.add(booking); db.commit(); db.refresh(booking)

    r = client.post(f"/admin/payments/{booking.id}/confirm", headers=care_auth)
    assert r.status_code == 200, r.text
