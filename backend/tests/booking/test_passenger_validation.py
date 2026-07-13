"""GEN-1 passenger name rules.

Direct-service tests against `lock_seats` (no HTTP layer). Each test seeds
a trip + seats + optional prior booking, then calls the service with a
list of PassengerInput-shaped objects to exercise the three rules:

  1. Each name must contain at least two whitespace-separated words.
  2. No two passengers in the same booking may share a normalized name.
  3. No passenger name may match one on an *active* booking for the trip
     (expired holds are freed).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.booking.service import lock_seats
from src.inventory.models import Route, Trip, Seat, Bus
from src.auth.models import User


def _pax(name, seat, phone=None, nid=None):
    """PassengerInput-shaped stand-in. lock_seats reads attributes, not fields."""
    return SimpleNamespace(
        full_name=name,
        phone_number=phone,
        national_id=nid,
        seat_number=seat,
    )


@pytest.fixture
def seeded_trip(db):
    """A trip with two available seats (1A, 1B). Returns (trip_id, seat_ids)."""
    provider = User(
        email="op@example.com", full_name="Op", password_hash="x",
        role="provider", status="active", email_verified=True,
    )
    db.add(provider)
    db.flush()

    route = Route(origin="Khartoum", destination="Port Sudan", duration="4h 20m")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus])
    db.flush()

    trip = Trip(
        route_id=route.id, provider_id=provider.id, bus_id=bus.id,
        departure_time=datetime.utcnow() + timedelta(days=1),
        price=8,
    )
    db.add(trip)
    db.flush()

    for name in ("1A", "1B"):
        db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))
    db.commit()
    return trip.id


def test_single_word_name_rejected(db, seeded_trip):
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db, trip_id=seeded_trip, seat_numbers=["1A"],
            customer_id=1, total_price=8,
            passengers=[_pax("Mohamed", "1A")],
        )
    assert exc.value.status_code == 400
    assert "at least two names" in exc.value.detail


def test_duplicate_in_same_booking_rejected(db, seeded_trip):
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db, trip_id=seeded_trip, seat_numbers=["1A", "1B"],
            customer_id=1, total_price=16,
            passengers=[
                _pax("Mohamed Ali", "1A"),
                _pax("MOHAMED ALI", "1B"),  # case + whitespace shouldn't help
            ],
        )
    assert exc.value.status_code == 400
    assert "1A" in exc.value.detail and "1B" in exc.value.detail
    assert "additional name" in exc.value.detail


def test_duplicate_against_existing_booking_rejected(db, seeded_trip):
    # First booking succeeds.
    lock_seats(
        db, trip_id=seeded_trip, seat_numbers=["1A"],
        customer_id=1, total_price=8,
        passengers=[_pax("Mohamed Ali", "1A")],
    )
    # Second booking on same trip with the same name is blocked.
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db, trip_id=seeded_trip, seat_numbers=["1B"],
            customer_id=2, total_price=8,
            passengers=[_pax("mohamed  ali", "1B")],
        )
    assert exc.value.status_code == 400
    assert "already booked on this trip" in exc.value.detail


def test_expired_booking_frees_the_name(db, seeded_trip):
    # First booking, then force it to expired (Reaper would do this in prod).
    r1 = lock_seats(
        db, trip_id=seeded_trip, seat_numbers=["1A"],
        customer_id=1, total_price=8,
        passengers=[_pax("Mohamed Ali", "1A")],
    )
    r1["booking"].status = "expired"
    db.commit()
    # New booking with the same name — the freed hold shouldn't block.
    lock_seats(
        db, trip_id=seeded_trip, seat_numbers=["1B"],
        customer_id=2, total_price=8,
        passengers=[_pax("Mohamed Ali", "1B")],
    )
    assert True  # no exception is the success signal


def test_distinct_two_word_names_pass(db, seeded_trip):
    r = lock_seats(
        db, trip_id=seeded_trip, seat_numbers=["1A", "1B"],
        customer_id=1, total_price=16,
        passengers=[
            _pax("Mohamed Ali", "1A"),
            _pax("Fatima Hassan", "1B"),
        ],
    )
    assert r["booking"].status == "pending"
    assert len(r["seats"]) == 2


def test_phone_and_id_are_optional(db, seeded_trip):
    """No phone or national_id → booking still succeeds (rules only govern names)."""
    r = lock_seats(
        db, trip_id=seeded_trip, seat_numbers=["1A"],
        customer_id=1, total_price=8,
        passengers=[_pax("Mohamed Ali", "1A")],  # phone=None, nid=None
    )
    assert r["booking"].status == "pending"
