"""Tests for GET /admin/providers/{provider_id}/reports endpoint."""
import datetime as _dt

from src.auth.models import User
from src.auth.utils import hash_password
from src.booking.models import Booking, Passenger
from src.inventory.models import Trip, Route, Bus


def test_provider_reports_happy_path(client, auth_header, db, provider_user):
    """Happy path: provider_reports returns same shape as /admin/reports
    with provider_id baked into the path."""
    # Seed a trip + confirmed booking with commission
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B",
              seat_layout_config={}, total_seats=45)
    db.add_all([route, bus])
    db.flush()
    trip = Trip(provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
                departure_time=_dt.datetime(2030, 1, 1), price=1000.0)
    db.add(trip)
    db.flush()

    # Create booking with passengers and commission snapshot
    booking = Booking(
        customer_id=1, trip_id=trip.id, status="confirmed",
        total_price=2000.0, channel="consumer", payment_status="paid",
        commission_amount=160.0, seat_ids=[1, 2],
        confirmed_at=_dt.datetime(2026, 3, 10),
    )
    db.add(booking)
    db.flush()

    # Add passengers to the booking
    p1 = Passenger(booking_id=booking.id, full_name="Alice Smith",
                   phone_number="249111", seat_number="1A")
    p2 = Passenger(booking_id=booking.id, full_name="Bob Jones",
                   phone_number="249222", seat_number="2A")
    db.add_all([p1, p2])
    db.commit()

    # Call the provider reports endpoint
    r = client.get(
        f"/admin/providers/{provider_user.id}/reports?from=2026-03&to=2026-03",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()

    # Verify shape matches ReportsResponse
    assert "period" in body
    assert body["period"]["from"] == "2026-03"
    assert body["period"]["to"] == "2026-03"

    # Verify financial section
    assert "financial" in body
    assert body["financial"]["total_commission"] == 160.0
    assert len(body["financial"]["by_month"]) == 1
    assert body["financial"]["by_month"][0]["month"] == "2026-03"
    assert body["financial"]["by_month"][0]["commission"] == 160.0
    assert body["financial"]["by_month"][0]["bookings"] == 1
    assert len(body["financial"]["by_provider"]) == 1
    assert body["financial"]["by_provider"][0]["provider_id"] == provider_user.id
    assert body["financial"]["by_provider"][0]["provider_name"] == provider_user.full_name
    assert body["financial"]["by_provider"][0]["commission"] == 160.0
    assert body["financial"]["by_provider"][0]["bookings"] == 1

    # Verify operational section
    assert "operational" in body
    assert body["operational"]["total_bookings"] == 1
    assert body["operational"]["total_passengers"] == 2
    assert len(body["operational"]["by_month"]) == 1
    assert body["operational"]["by_month"][0]["month"] == "2026-03"
    assert body["operational"]["by_month"][0]["bookings"] == 1
    assert body["operational"]["by_month"][0]["passengers"] == 2
    assert body["operational"]["by_month"][0]["consumer"] == 1
    assert body["operational"]["by_month"][0]["walkin"] == 0
    assert len(body["operational"]["by_provider"]) == 1
    assert body["operational"]["by_provider"][0]["provider_id"] == provider_user.id
    assert body["operational"]["by_provider"][0]["bookings"] == 1
    assert body["operational"]["by_provider"][0]["passengers"] == 2


def test_provider_reports_non_admin_403(client, db, provider_user):
    """Non-admin (provider or customer) tries to hit endpoint -> 403."""
    # Authenticate as provider
    r_login = client.post("/auth/login", json={
        "email": provider_user.email,
        "password": "Test#2026",
    })
    assert r_login.status_code == 200
    provider_auth = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

    r = client.get(
        f"/admin/providers/{provider_user.id}/reports?from=2026-03&to=2026-03",
        headers=provider_auth,
    )
    assert r.status_code == 403


def test_provider_reports_unknown_provider_404(client, auth_header):
    """Unknown provider_id in path -> 404."""
    r = client.get(
        "/admin/providers/999/reports?from=2026-03&to=2026-03",
        headers=auth_header,
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "Provider not found"


def test_provider_reports_non_provider_user_404(client, auth_header, db):
    """If the id exists but is not a provider (e.g., customer) -> 404."""
    # Create a customer user
    from src.auth.utils import hash_password
    cust = User(
        email="customer@x.com",
        full_name="Customer Test",
        password_hash=hash_password("Test#2026"),
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(cust)
    db.commit()

    r = client.get(
        f"/admin/providers/{cust.id}/reports?from=2026-03&to=2026-03",
        headers=auth_header,
    )
    assert r.status_code == 404
