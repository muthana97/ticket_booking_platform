"""GET /bookings/{id}/ticket — access rules.

Care admin was added 2026-07-30 as a restricted admin tier for customer-
care agents. Their whole job is answering "what's the status of booking
BOK-XXXX-XX?" on customer calls, so the ticket endpoint MUST accept
care_admin alongside admin. This lives here (not in test_care_admin_role)
because it's the booking router's access rule, not an /admin/* gate.
"""
from datetime import datetime, timedelta

import pytest

from src.auth.models import User
from src.auth.utils import hash_password
from src.booking.models import Booking
from src.inventory.models import Route, Bus, Trip


@pytest.fixture
def owning_provider(db):
    u = User(
        email="tkt-own@x.com", full_name="Ticket Owner",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def customer(db):
    u = User(
        email="tkt-cust@x.com", full_name="Ticket Customer",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def care_admin(db):
    u = User(
        email="tkt-care@x.com", full_name="Ticket Care",
        password_hash=hash_password("Test#2026"),
        role="care_admin", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def trip(db, owning_provider):
    route = Route(origin="K", destination="P", duration="4h")
    bus = Bus(provider_id=owning_provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=owning_provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=1), price=100,
    )
    db.add(t); db.commit(); db.refresh(t); return t


@pytest.fixture
def issued_booking(db, trip, customer):
    """A committed booking with a billing_reference minted — ticket-readable."""
    b = Booking(
        customer_id=customer.id, trip_id=trip.id, status="confirmed",
        total_price=100, channel="consumer", payment_status="paid",
        payment_method="cash",
        commission_amount=5.0, seat_ids=[1],
        billing_reference="BOK-TEST-CA",
        bill_generated_at=datetime.utcnow(),
        confirmed_at=datetime.utcnow(),
    )
    db.add(b); db.commit(); db.refresh(b); return b


def _auth_for(client, user):
    r = client.post("/auth/login", json={"email": user.email, "password": "Test#2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_care_admin_can_view_any_ticket(client, care_admin, issued_booking):
    """Care admin needs this to answer customer support calls."""
    headers = _auth_for(client, care_admin)
    r = client.get(f"/bookings/{issued_booking.id}/ticket", headers=headers)
    assert r.status_code == 200, r.text
    # Payload actually loads (not a routing accident)
    assert "BOK-TEST-CA" in r.text


def test_admin_still_can_view_any_ticket(client, auth_header, issued_booking):
    """Regression: broadening the check to include care_admin must not break
    the full-admin path."""
    r = client.get(f"/bookings/{issued_booking.id}/ticket", headers=auth_header)
    assert r.status_code == 200, r.text


def test_customer_owner_still_can_view_own_ticket(client, customer, issued_booking):
    headers = _auth_for(client, customer)
    r = client.get(f"/bookings/{issued_booking.id}/ticket", headers=headers)
    assert r.status_code == 200, r.text


def test_owning_provider_still_can_view_ticket_on_own_trip(
    client, owning_provider, issued_booking,
):
    headers = _auth_for(client, owning_provider)
    r = client.get(f"/bookings/{issued_booking.id}/ticket", headers=headers)
    assert r.status_code == 200, r.text


def test_other_customer_still_cannot_view_someone_elses_ticket(
    client, db, issued_booking,
):
    """Regression: broadening for care_admin must not accidentally admit
    other customers."""
    other = User(
        email="tkt-other@x.com", full_name="Other Cust",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(other); db.commit()
    headers = _auth_for(client, other)
    r = client.get(f"/bookings/{issued_booking.id}/ticket", headers=headers)
    assert r.status_code == 403
