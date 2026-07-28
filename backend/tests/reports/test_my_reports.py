"""GET /reports/mine — provider-scoped self-service reports.

Seven scenarios: cap-off 403, cap-on happy path, cross-provider scope,
default period, explicit period, unauth 401, and customer-role 403.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password


@pytest.fixture
def provider_with_reports(db):
    """A provider WITH the reports capability enabled."""
    u = User(
        email="p-reports@x.com", full_name="Provider With Reports",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
        can_view_reports=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def provider_without_reports(db):
    """A provider WITHOUT the reports capability (the default state)."""
    u = User(
        email="p-noreports@x.com", full_name="Provider No Reports",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
        # can_view_reports defaults to False
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def customer(db):
    u = User(
        email="c-reports@x.com", full_name="Customer",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "Test#2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_my_reports_403_when_cap_off(client, provider_without_reports):
    """A provider whose cap is off (the default) gets 403 with the exact
    documented detail string — even if they somehow reached the endpoint
    (e.g. stale client, direct API call, race with an admin toggle)."""
    headers = _login(client, provider_without_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == (
        "Reports are not enabled for your account. Contact an administrator."
    )


def test_my_reports_200_when_cap_on(client, provider_with_reports):
    """Cap on → 200 with the trimmed response shape (no by_provider arrays)."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "period" in body
    assert "financial" in body and "by_month" in body["financial"]
    assert "operational" in body and "by_month" in body["operational"]
    # by_provider arrays MUST be trimmed — pointless for a single-provider view
    assert "by_provider" not in body["financial"]
    assert "by_provider" not in body["operational"]
    # Headline totals preserved
    assert "total_commission" in body["financial"]
    assert "total_bookings" in body["operational"]
    assert "total_passengers" in body["operational"]


def test_my_reports_default_period_last_6_months(client, provider_with_reports):
    """No from/to → default 6-month window (5 months ago through current)."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200, r.text
    period = r.json()["period"]
    # Both from and to are YYYY-MM strings; the span must be 6 months inclusive
    fy, fm = map(int, period["from"].split("-"))
    ty, tm = map(int, period["to"].split("-"))
    months = (ty - fy) * 12 + (tm - fm) + 1
    assert months == 6


def test_my_reports_respects_from_to(client, provider_with_reports):
    """Explicit from/to → response period reflects them."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine?from=2026-01&to=2026-03", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["period"] == {"from": "2026-01", "to": "2026-03"}


def test_my_reports_scoped_to_own_provider_id(client, db, provider_with_reports):
    """Even with two providers in the DB, /reports/mine only sees the caller's
    data. Uses a booking on a foreign provider to prove the scope filter is
    real, not vacuous."""
    from src.inventory.models import Trip, Route, Bus
    from src.booking.models import Booking
    from datetime import datetime, timezone, timedelta

    # A DIFFERENT provider with confirmed booking activity in the current window.
    other = User(
        email="p-other@x.com", full_name="Other Provider",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(other); db.commit(); db.refresh(other)

    route = Route(origin="Khartoum", destination="Port Sudan", duration="10h")
    bus = Bus(provider_id=other.id, name="Other Bus",
              seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.commit(); db.refresh(route); db.refresh(bus)

    trip = Trip(
        provider_id=other.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.now(timezone.utc) + timedelta(days=3),
        price=100,
    )
    db.add(trip); db.commit(); db.refresh(trip)

    booking = Booking(
        trip_id=trip.id,
        status="confirmed",
        total_price=1000, channel="consumer",
        commission_amount=100,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(booking); db.commit()

    # Now call /reports/mine as provider_with_reports — should NOT see other's data.
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # Caller has no bookings → totals stay zero
    assert body["financial"]["total_commission"] == 0
    assert body["operational"]["total_bookings"] == 0


def test_my_reports_401_when_unauth(client):
    """No Authorization header → 401 from the auth dependency."""
    r = client.get("/reports/mine")
    assert r.status_code == 401


def test_my_reports_403_when_customer(client, customer):
    """A customer hitting the endpoint gets 403 from the role guard —
    doesn't matter what their cap state is."""
    headers = _login(client, customer.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 403
