import datetime as _dt

import pytest

from src.booking.models import Booking
from src.booking.models import Passenger
from src.finance.reports import (
    period_months, financial_by_month, financial_by_provider,
    operational_by_month, operational_by_provider,
)
from src.inventory.models import Trip, Route, Bus


def test_period_months_single_month():
    assert period_months("2026-06", "2026-06") == ["2026-06"]


def test_period_months_inclusive_range():
    assert period_months("2026-01", "2026-06") == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"
    ]


def test_period_months_spans_year():
    assert period_months("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02"
    ]


@pytest.fixture
def trip(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B",
              seat_layout_config={}, total_seats=45)
    db.add_all([route, bus])
    db.flush()
    t = Trip(provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
             departure_time=_dt.datetime(2030, 1, 1), price=1000.0)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _booking(db, trip, *, total=1000.0, commission=80.0, when=None,
             channel="consumer", status="confirmed"):
    b = Booking(
        customer_id=1, trip_id=trip.id, status=status,
        total_price=total, channel=channel, payment_status="paid",
        commission_amount=commission, seat_ids=[1],
        confirmed_at=when or _dt.datetime(2026, 3, 15),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def test_financial_by_month_empty_period(db, trip):
    rows = financial_by_month(
        db, period=period_months("2026-01", "2026-02"), provider_id=None,
    )
    assert rows == [
        {"month": "2026-01", "commission": 0.0, "bookings": 0},
        {"month": "2026-02", "commission": 0.0, "bookings": 0},
    ]


def test_financial_by_month_one_booking(db, trip):
    _booking(db, trip, total=2000.0, commission=160.0,
             when=_dt.datetime(2026, 3, 15))
    rows = financial_by_month(
        db, period=period_months("2026-01", "2026-04"), provider_id=None,
    )
    assert rows == [
        {"month": "2026-01", "commission": 0.0,   "bookings": 0},
        {"month": "2026-02", "commission": 0.0,   "bookings": 0},
        {"month": "2026-03", "commission": 160.0, "bookings": 1},
        {"month": "2026-04", "commission": 0.0,   "bookings": 0},
    ]


def test_financial_by_month_excludes_null_commission(db, trip):
    """Historic pre-feature bookings (commission_amount IS NULL) don't count."""
    _booking(db, trip, total=1000.0, commission=None,
             when=_dt.datetime(2026, 3, 15))
    rows = financial_by_month(db, period=["2026-03", "2026-03"], provider_id=None)
    assert rows == [{"month": "2026-03", "commission": 0.0, "bookings": 0}]


def test_financial_by_month_walkin_counts_with_zero(db, trip):
    """Walk-ins have commission_amount=0.0 (not NULL) — included in count, 0 sum."""
    _booking(db, trip, total=1000.0, commission=0.0,
             channel="walkin", when=_dt.datetime(2026, 3, 15))
    rows = financial_by_month(db, period=["2026-03", "2026-03"], provider_id=None)
    assert rows == [{"month": "2026-03", "commission": 0.0, "bookings": 1}]


def test_financial_by_provider_empty(db, trip):
    rows = financial_by_provider(db, period=["2026-01", "2026-02"], provider_id=None)
    assert rows == []


def test_financial_by_provider_groups_per_provider(db, trip, provider_user):
    # Two bookings on the same provider in range, one outside.
    _booking(db, trip, commission=100.0, when=_dt.datetime(2026, 3, 5))
    _booking(db, trip, commission=200.0, when=_dt.datetime(2026, 3, 20))
    _booking(db, trip, commission=999.0, when=_dt.datetime(2026, 5, 1))  # out of range

    rows = financial_by_provider(
        db, period=["2026-03", "2026-03"], provider_id=None,
    )
    assert rows == [
        {"provider_id": provider_user.id,
         "provider_name": provider_user.full_name,
         "commission": 300.0, "bookings": 2},
    ]


def test_financial_by_provider_filter(db, trip, provider_user):
    _booking(db, trip, commission=100.0, when=_dt.datetime(2026, 3, 5))
    rows = financial_by_provider(
        db, period=["2026-03", "2026-03"], provider_id=provider_user.id + 999,
    )
    assert rows == []


def _with_passengers(db, booking, n):
    for i in range(n):
        db.add(Passenger(
            booking_id=booking.id,
            full_name=f"Pax {i+1}",
            phone_number="249111",
            seat_number=f"{i+1}A",
        ))
    db.commit()
    return booking


def test_operational_by_month_counts_all_confirmed(db, trip):
    """Even bookings with NULL commission count operationally."""
    b1 = _booking(db, trip, commission=None, when=_dt.datetime(2026, 3, 5))
    _with_passengers(db, b1, 2)
    rows = operational_by_month(db, period=["2026-03", "2026-03"], provider_id=None)
    assert rows == [{"month": "2026-03", "bookings": 1, "passengers": 2,
                     "consumer": 1, "walkin": 0}]


def test_operational_by_month_consumer_vs_walkin_split(db, trip):
    b1 = _booking(db, trip, channel="consumer", commission=80.0,
                  when=_dt.datetime(2026, 4, 1))
    _with_passengers(db, b1, 2)
    b2 = _booking(db, trip, channel="walkin", commission=0.0,
                  when=_dt.datetime(2026, 4, 15))
    _with_passengers(db, b2, 3)
    rows = operational_by_month(db, period=["2026-04", "2026-04"], provider_id=None)
    assert rows == [{"month": "2026-04", "bookings": 2, "passengers": 5,
                     "consumer": 1, "walkin": 1}]


def test_operational_by_provider_groups_and_splits(db, trip, provider_user):
    b1 = _booking(db, trip, channel="consumer", commission=100.0,
                  when=_dt.datetime(2026, 3, 5))
    _with_passengers(db, b1, 2)
    b2 = _booking(db, trip, channel="walkin", commission=0.0,
                  when=_dt.datetime(2026, 3, 12))
    _with_passengers(db, b2, 1)

    rows = operational_by_provider(
        db, period=["2026-03", "2026-03"], provider_id=None,
    )
    assert rows == [{
        "provider_id": provider_user.id,
        "provider_name": provider_user.full_name,
        "bookings": 2, "passengers": 3,
        "consumer": 1, "walkin": 1,
    }]
