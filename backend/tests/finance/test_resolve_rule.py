import datetime as _dt

import pytest

from src.finance.models import CommissionRule
from src.finance.service import resolve_rule
from src.inventory.models import Trip, Route, Bus


@pytest.fixture
def trip(db, provider_user):
    route = Route(origin="Khartoum", destination="Port Sudan", duration="10h")
    bus = Bus(
        provider_id=provider_user.id, name="B1",
        seat_layout_config={"rows": 10, "config": "2x2"}, total_seats=45,
    )
    db.add_all([route, bus])
    db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=_dt.datetime(2030, 1, 1, 12, 0),
        price=1000.0,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _mk(scope, **kw):
    v = kw.pop("v", 5.0)
    return CommissionRule(scope=scope, rate_kind="percentage", rate_value=v, **kw)


def test_no_rules_returns_none(db, trip):
    assert resolve_rule(db, trip) is None


def test_global_only(db, trip):
    db.add(_mk("global", v=10.0))
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "global" and r.rate_value == 10.0


def test_provider_beats_global(db, trip):
    db.add_all([
        _mk("global", v=10.0),
        _mk("provider", provider_id=trip.provider_id, v=8.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "provider" and r.rate_value == 8.0


def test_provider_route_beats_provider(db, trip):
    db.add_all([
        _mk("global", v=10.0),
        _mk("provider", provider_id=trip.provider_id, v=8.0),
        _mk("provider_route",
            provider_id=trip.provider_id, route_id=trip.route_id, v=6.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "provider_route" and r.rate_value == 6.0


def test_trip_beats_everything(db, trip):
    db.add_all([
        _mk("global", v=10.0),
        _mk("provider", provider_id=trip.provider_id, v=8.0),
        _mk("provider_route",
            provider_id=trip.provider_id, route_id=trip.route_id, v=6.0),
        _mk("trip",
            provider_id=trip.provider_id, trip_id=trip.id, v=4.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "trip" and r.rate_value == 4.0


def test_other_provider_rules_ignored(db, trip):
    """A rule for a DIFFERENT real provider must not win for our trip."""
    from src.auth.models import User
    from src.auth.utils import hash_password
    other = User(
        email="other-provider@tazkirati.app",
        full_name="Other Provider",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add_all([
        _mk("provider", provider_id=other.id, v=8.0),
        _mk("global", v=10.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "global" and r.rate_value == 10.0
