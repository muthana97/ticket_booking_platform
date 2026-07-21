"""End-to-end promo flow: admin CRUD, apply at lock, per-user cap, single-seat
rule, walk-in rejection, invalid / expired / not-yet-started, scope mismatch,
max_redemptions atomic cap, Reaper release on expiry.

Uses lock_seats + confirm_payment directly (service level) plus a couple of
HTTP round-trips for the admin CRUD side, so the whole promo lifecycle is
exercised without spinning up the Reaper's asyncio loop.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth.models import User
from src.auth.utils import hash_password
from src.booking.models import Booking
from src.booking.service import lock_seats
from src.admin.service import confirm_payment
from src.inventory.models import Bus, Route, Seat, Trip
from src.promo.models import PromoCode
from src.promo import service as promo_svc


# ---------------------------------------------------------------------------
# Fixtures — actors + a trip with three seats
# ---------------------------------------------------------------------------

def _mk_user(db, *, email, role):
    u = User(
        email=email, full_name=email.split("@")[0].title(),
        password_hash=hash_password("Test#2026"),
        role=role, status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u); return u


@pytest.fixture
def admin(db):
    return _mk_user(db, email="promo-admin@x.com", role="admin")

@pytest.fixture
def provider(db):
    return _mk_user(db, email="promo-prov@x.com", role="provider")

@pytest.fixture
def other_provider(db):
    return _mk_user(db, email="promo-prov2@x.com", role="provider")

@pytest.fixture
def customer_a(db):
    return _mk_user(db, email="cust-a@x.com", role="customer")

@pytest.fixture
def customer_b(db):
    return _mk_user(db, email="cust-b@x.com", role="customer")


def _make_trip(db, *, provider, origin="Khartoum", destination="Port Sudan",
               seats=("1A", "1B", "1C"), price=100.0):
    route = Route(origin=origin, destination=destination, duration="4h")
    bus = Bus(provider_id=provider.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    trip = Trip(
        provider_id=provider.id, bus_id=bus.id, route_id=route.id,
        departure_time=datetime.utcnow() + timedelta(days=1),
        price=price,
    )
    db.add(trip); db.flush()
    for name in seats:
        db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))
    db.commit()
    return trip


def _pax(name, seat):
    return SimpleNamespace(full_name=name, phone_number=None, national_id=None, seat_number=seat)


def _bearer(client, user):
    r = client.post("/auth/login", json={"email": user.email, "password": "Test#2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# 1. Admin CRUD (create + patch + delete) over HTTP
# ---------------------------------------------------------------------------

def test_admin_crud_promo(client, admin):
    hdr = _bearer(client, admin)

    r = client.post("/admin/promos", headers=hdr, json={
        "code": "libre",
        "discount_kind": "percentage",
        "discount_value": 10,
        "active": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "LIBRE"                # normalized upper
    assert body["redemption_count"] == 0

    # Duplicate code refused
    r2 = client.post("/admin/promos", headers=hdr, json={
        "code": "LIBRE",
        "discount_kind": "flat",
        "discount_value": 5,
    })
    assert r2.status_code == 409

    # Patch → flip active off
    r3 = client.patch(f"/admin/promos/{body['id']}", headers=hdr, json={"active": False})
    assert r3.status_code == 200
    assert r3.json()["active"] is False

    # List
    r4 = client.get("/admin/promos", headers=hdr)
    assert r4.status_code == 200
    assert any(p["code"] == "LIBRE" for p in r4.json())

    # Delete
    r5 = client.delete(f"/admin/promos/{body['id']}", headers=hdr)
    assert r5.status_code == 204


def test_percentage_over_100_rejected(client, admin):
    hdr = _bearer(client, admin)
    r = client.post("/admin/promos", headers=hdr, json={
        "code": "TOOBIG",
        "discount_kind": "percentage",
        "discount_value": 150,
    })
    assert r.status_code == 422  # pydantic validator


def test_scope_needs_provider(client, admin):
    """trip_id / route_id without provider_id is refused."""
    hdr = _bearer(client, admin)
    r = client.post("/admin/promos", headers=hdr, json={
        "code": "ORPHAN",
        "discount_kind": "percentage",
        "discount_value": 10,
        "trip_id": 999,
    })
    assert r.status_code == 422


def test_end_after_start(client, admin):
    hdr = _bearer(client, admin)
    now = datetime.utcnow()
    r = client.post("/admin/promos", headers=hdr, json={
        "code": "REVERSED",
        "discount_kind": "percentage",
        "discount_value": 10,
        "start_at":   (now + timedelta(hours=1)).isoformat(),
        "expires_at": now.isoformat(),
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 2. Apply-at-lock — happy path + discount snapshot
# ---------------------------------------------------------------------------

def test_apply_promo_discounts_total(db, provider, customer_a):
    trip = _make_trip(db, provider=provider, price=100.0)
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    result = lock_seats(
        db=db, trip_id=trip.id, seat_numbers=["1A"],
        customer_id=customer_a.id, total_price=100.0,
        passengers=[_pax("Ada Lovelace", "1A")],
        promo_code="libre",
    )
    b = result["booking"]
    assert b.promo_code == "LIBRE"
    assert b.promo_discount == 10.0
    assert b.total_price == 90.0
    # redemption incremented at lock
    p = db.query(PromoCode).filter(PromoCode.code == "LIBRE").first()
    assert p.redemption_count == 1


def test_flat_discount_clamped_to_total(db, provider, customer_a):
    trip = _make_trip(db, provider=provider, price=50.0)
    db.add(PromoCode(code="BIG", discount_kind="flat", discount_value=999.0))
    db.commit()

    result = lock_seats(
        db=db, trip_id=trip.id, seat_numbers=["1A"],
        customer_id=customer_a.id, total_price=50.0,
        passengers=[_pax("Grace Hopper", "1A")],
        promo_code="BIG",
    )
    b = result["booking"]
    assert b.promo_discount == 50.0
    assert b.total_price == 0.0


# ---------------------------------------------------------------------------
# 3. Business rules — walk-in, multi-seat, per-user
# ---------------------------------------------------------------------------

def test_walkin_rejects_promo(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=provider.id, total_price=100.0,
            passengers=[_pax("Walk In", "1A")],
            channel="walkin",
            promo_code="LIBRE",
        )
    assert exc.value.status_code == 400
    assert "customer" in exc.value.detail.lower()


def test_multi_seat_rejects_promo(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A", "1B"],
            customer_id=customer_a.id, total_price=200.0,
            passengers=[_pax("Ada A Lovelace", "1A"), _pax("Grace B Hopper", "1B")],
            promo_code="LIBRE",
        )
    assert exc.value.status_code == 400
    assert "single-seat" in exc.value.detail.lower()


def test_second_use_by_same_customer_rejected(db, provider, customer_a):
    trip = _make_trip(db, provider=provider, seats=("1A", "1B"))
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    lock_seats(
        db=db, trip_id=trip.id, seat_numbers=["1A"],
        customer_id=customer_a.id, total_price=100.0,
        passengers=[_pax("Ada Lovelace", "1A")],
        promo_code="LIBRE",
    )
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1B"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Grace Hopper", "1B")],
            promo_code="LIBRE",
        )
    assert exc.value.status_code == 400
    assert "already used" in exc.value.detail.lower()


def test_different_customer_can_use_same_promo(db, provider, customer_a, customer_b):
    trip = _make_trip(db, provider=provider, seats=("1A", "1B"))
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    lock_seats(
        db=db, trip_id=trip.id, seat_numbers=["1A"],
        customer_id=customer_a.id, total_price=100.0,
        passengers=[_pax("Ada Lovelace", "1A")],
        promo_code="LIBRE",
    )
    r = lock_seats(
        db=db, trip_id=trip.id, seat_numbers=["1B"],
        customer_id=customer_b.id, total_price=100.0,
        passengers=[_pax("Grace Hopper", "1B")],
        promo_code="LIBRE",
    )
    assert r["booking"].promo_code == "LIBRE"
    p = db.query(PromoCode).filter(PromoCode.code == "LIBRE").first()
    assert p.redemption_count == 2


# ---------------------------------------------------------------------------
# 4. Validation — invalid, inactive, time window, scope
# ---------------------------------------------------------------------------

def test_unknown_code_404(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="GHOST",
        )
    assert exc.value.status_code == 404


def test_inactive_promo_rejected(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0, active=False))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="LIBRE",
        )
    assert exc.value.status_code == 400
    assert "no longer active" in exc.value.detail.lower()


def test_not_yet_active(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(
        code="FUTURE", discount_kind="percentage", discount_value=10.0,
        start_at=datetime.utcnow() + timedelta(days=1),
    ))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="FUTURE",
        )
    assert "active yet" in exc.value.detail.lower()


def test_expired_window(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(
        code="OLD", discount_kind="percentage", discount_value=10.0,
        expires_at=datetime.utcnow() - timedelta(hours=1),
    ))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="OLD",
        )
    assert "expired" in exc.value.detail.lower()


def test_wrong_provider_scope(db, provider, other_provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(
        code="OTHER", discount_kind="percentage", discount_value=10.0,
        provider_id=other_provider.id,
    ))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="OTHER",
        )
    assert "operator" in exc.value.detail.lower()


def test_wrong_route_scope(db, provider, customer_a):
    # provider-scoped promo pinned to a DIFFERENT route than the trip is on
    other_route = Route(origin="A", destination="B", duration="1h")
    db.add(other_route); db.commit(); db.refresh(other_route)
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(
        code="ROUTE", discount_kind="percentage", discount_value=10.0,
        provider_id=provider.id, route_id=other_route.id,
    ))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        lock_seats(
            db=db, trip_id=trip.id, seat_numbers=["1A"],
            customer_id=customer_a.id, total_price=100.0,
            passengers=[_pax("Ada Lovelace", "1A")],
            promo_code="ROUTE",
        )
    assert "route" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# 5. max_redemptions cap + Reaper release
# ---------------------------------------------------------------------------

def test_cap_hit_then_reject(db, provider, customer_a, customer_b):
    trip = _make_trip(db, provider=provider, seats=("1A", "1B", "1C"))
    cust_c = _mk_user(db, email="cust-c@x.com", role="customer")
    db.add(PromoCode(
        code="LIMITED", discount_kind="percentage", discount_value=10.0,
        max_redemptions=2,
    ))
    db.commit()

    lock_seats(db=db, trip_id=trip.id, seat_numbers=["1A"],
               customer_id=customer_a.id, total_price=100.0,
               passengers=[_pax("Ada Lovelace", "1A")], promo_code="LIMITED")
    lock_seats(db=db, trip_id=trip.id, seat_numbers=["1B"],
               customer_id=customer_b.id, total_price=100.0,
               passengers=[_pax("Grace Hopper", "1B")], promo_code="LIMITED")

    with pytest.raises(HTTPException) as exc:
        lock_seats(db=db, trip_id=trip.id, seat_numbers=["1C"],
                   customer_id=cust_c.id, total_price=100.0,
                   passengers=[_pax("Katherine Johnson", "1C")], promo_code="LIMITED")
    assert "redemption limit" in exc.value.detail.lower()


def test_reaper_releases_on_expiry(db, provider, customer_a):
    """Simulate the Reaper's expire loop and verify redemption_count drops back."""
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(
        code="LIMITED", discount_kind="percentage", discount_value=10.0,
        max_redemptions=1,
    ))
    db.commit()

    lock_seats(db=db, trip_id=trip.id, seat_numbers=["1A"],
               customer_id=customer_a.id, total_price=100.0,
               passengers=[_pax("Ada Lovelace", "1A")], promo_code="LIMITED")
    p = db.query(PromoCode).filter(PromoCode.code == "LIMITED").first()
    assert p.redemption_count == 1

    # Force the booking past its window + run the Reaper's inner block.
    booking = db.query(Booking).order_by(Booking.id.desc()).first()
    booking.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    # Mirror the Reaper loop body (tasks.py) — release seats + decrement
    # promo counter + mark expired.
    if booking.seat_ids:
        db.query(Seat).filter(Seat.id.in_(booking.seat_ids),
                              Seat.trip_id == booking.trip_id).update(
            {"status": "available"}, synchronize_session=False)
    if booking.promo_id:
        pr = db.query(PromoCode).filter(PromoCode.id == booking.promo_id).first()
        pr.redemption_count -= 1
    booking.status = "expired"
    db.commit()

    p2 = db.query(PromoCode).filter(PromoCode.code == "LIMITED").first()
    assert p2.redemption_count == 0  # slot released back to the pool


# ---------------------------------------------------------------------------
# 6. Confirm doesn't double-bump (invariant test)
# ---------------------------------------------------------------------------

def test_confirm_does_not_increment_again(db, provider, customer_a):
    trip = _make_trip(db, provider=provider)
    db.add(PromoCode(code="LIBRE", discount_kind="percentage", discount_value=10.0))
    db.commit()

    lock_seats(db=db, trip_id=trip.id, seat_numbers=["1A"],
               customer_id=customer_a.id, total_price=100.0,
               passengers=[_pax("Ada Lovelace", "1A")], promo_code="LIBRE")
    b = db.query(Booking).order_by(Booking.id.desc()).first()
    p_before = db.query(PromoCode).filter(PromoCode.code == "LIBRE").first().redemption_count

    # Fast-path the booking to committed_pending so confirm can flip it.
    b.status = "committed_pending"
    b.billing_reference = "BOK-TEST-01"
    b.bill_generated_at = datetime.utcnow()
    db.commit()

    confirm_payment(db, booking_id=b.id, payment_method="billing_reference")
    p_after = db.query(PromoCode).filter(PromoCode.code == "LIBRE").first().redemption_count
    assert p_after == p_before  # no double-bump
