import datetime as _dt

import pytest

from src.admin.service import confirm_payment
from src.booking.models import Booking
from src.finance.models import CommissionRule
from src.inventory.models import Trip, Route, Bus, Seat


@pytest.fixture
def trip_with_seats(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(
        provider_id=provider_user.id, name="B",
        seat_layout_config={}, total_seats=45,
    )
    db.add_all([route, bus])
    db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=_dt.datetime(2030, 1, 1),
        price=1000.0,
    )
    db.add(t)
    db.flush()
    seats = [
        Seat(trip_id=t.id, seat_number=f"{i}A", status="locked")
        for i in range(1, 3)
    ]
    db.add_all(seats)
    db.commit()
    return t, seats


def _committed_booking(db, trip, seats, *, channel="consumer", total=2000.0):
    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=total, channel=channel, payment_status="unpaid",
        seat_ids=[s.id for s in seats],
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def test_consumer_confirm_snapshots_commission(db, trip_with_seats):
    trip, seats = trip_with_seats
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=8.0))
    db.commit()
    b = _committed_booking(db, trip, seats, total=2000.0)
    confirm_payment(db, booking_id=b.id, actor_user_id=trip.provider_id)
    db.refresh(b)
    assert b.status == "confirmed"
    assert b.commission_amount == 160.0
    assert b.commission_rate_kind == "percentage"
    assert b.confirmed_at is not None


def test_walkin_confirm_zero_commission_even_with_rule(db, trip_with_seats):
    trip, seats = trip_with_seats
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = _committed_booking(db, trip, seats, channel="walkin", total=2000.0)
    confirm_payment(db, booking_id=b.id, payment_method="cash", actor_user_id=trip.provider_id)
    db.refresh(b)
    assert b.status == "confirmed"
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rule_id is None
    assert b.confirmed_at is not None  # set on every confirmation, walk-in or not


def test_confirm_without_rules_zero(db, trip_with_seats):
    trip, seats = trip_with_seats
    b = _committed_booking(db, trip, seats)
    confirm_payment(db, booking_id=b.id, actor_user_id=trip.provider_id)
    db.refresh(b)
    assert b.commission_amount == 0.0
