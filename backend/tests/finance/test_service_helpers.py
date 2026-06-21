import datetime as _dt

import pytest
from fastapi import HTTPException

from src.finance.models import CommissionRule
from src.finance import service as fin
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
        departure_time=_dt.datetime(2030, 1, 1, 12, 0),
        price=1000.0,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_upsert_global_inserts_when_missing(db):
    rule = fin.upsert_global(db, rate_kind="percentage", rate_value=8.0)
    assert rule.id is not None
    assert rule.scope == "global"


def test_upsert_global_updates_singleton(db):
    fin.upsert_global(db, rate_kind="percentage", rate_value=8.0)
    rule = fin.upsert_global(db, rate_kind="flat_per_seat", rate_value=150.0)
    assert db.query(CommissionRule).filter_by(scope="global").count() == 1
    assert rule.rate_kind == "flat_per_seat"


def test_create_override_provider(db, provider_user):
    o = fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=8.0,
    )
    assert o.id is not None
    assert o.scope == "provider"


def test_create_override_duplicate_raises_409(db, provider_user):
    fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=8.0,
    )
    with pytest.raises(HTTPException) as exc:
        fin.create_override(
            db, scope="provider", provider_id=provider_user.id,
            route_id=None, trip_id=None,
            rate_kind="percentage", rate_value=10.0,
        )
    assert exc.value.status_code == 409


def test_create_override_trip_must_belong_to_provider(db, provider_user, trip):
    other_provider_id = provider_user.id + 999
    with pytest.raises(HTTPException) as exc:
        fin.create_override(
            db, scope="trip", provider_id=other_provider_id,
            route_id=None, trip_id=trip.id,
            rate_kind="percentage", rate_value=5.0,
        )
    assert exc.value.status_code == 400


def test_list_overrides_decorates(db, provider_user, trip):
    fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=8.0,
    )
    fin.create_override(
        db, scope="trip", provider_id=provider_user.id,
        route_id=None, trip_id=trip.id,
        rate_kind="percentage", rate_value=4.0,
    )
    rows = fin.list_overrides(db)
    assert rows[0]["scope"] == "trip"
    assert rows[0]["trip_label"].startswith(f"Trip #{trip.id}")
    assert rows[0]["provider_name"] == provider_user.full_name
    assert rows[1]["scope"] == "provider"


def test_update_override(db, provider_user):
    o = fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=8.0,
    )
    updated = fin.update_override(
        db, override_id=o.id,
        rate_kind="flat_per_seat", rate_value=200.0,
    )
    assert updated.rate_kind == "flat_per_seat" and updated.rate_value == 200.0


def test_delete_override(db, provider_user):
    o = fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=8.0,
    )
    fin.delete_override(db, override_id=o.id)
    assert db.query(CommissionRule).filter_by(id=o.id).count() == 0


def test_delete_override_404(db):
    with pytest.raises(HTTPException) as exc:
        fin.delete_override(db, override_id=9999)
    assert exc.value.status_code == 404
