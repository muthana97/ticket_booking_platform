import datetime as _dt

import pytest

from src.booking.models import Booking
from src.finance.models import CommissionRule
from src.finance.service import snapshot_commission
from src.inventory.models import Trip, Route, Bus


@pytest.fixture
def trip(db, provider_user):
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
    db.commit()
    db.refresh(t)
    return t


def _booking(trip, *, channel="consumer", total=2000.0, seats=2):
    return Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=total, channel=channel, payment_status="unpaid",
        seat_ids=list(range(1, seats + 1)),
    )


def test_no_rule_sets_zero(db, trip):
    b = _booking(trip)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rule_id is None


def test_percentage_rule(db, trip):
    rule = CommissionRule(scope="global", rate_kind="percentage", rate_value=8.0)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    b = _booking(trip, total=2000.0)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 160.0
    assert b.commission_rate_kind == "percentage"
    assert b.commission_rate_value == 8.0
    assert b.commission_rule_id == rule.id


def test_flat_per_seat_rule(db, trip):
    rule = CommissionRule(scope="global", rate_kind="flat_per_seat", rate_value=150.0)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    b = _booking(trip, total=2000.0, seats=2)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 300.0
    assert b.commission_rate_kind == "flat_per_seat"
    assert b.commission_rate_value == 150.0


def test_walkin_always_zero_even_with_rule(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = _booking(trip, channel="walkin", total=2000.0)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rate_value is None
    assert b.commission_rule_id is None


def test_percentage_rounds_to_two_decimals(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=7.5))
    db.commit()
    b = _booking(trip, total=333.33)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 25.0


def test_empty_seat_ids_flat_yields_zero(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="flat_per_seat", rate_value=150.0))
    db.commit()
    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=0.0, channel="consumer", payment_status="unpaid",
        seat_ids=[],
    )
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
