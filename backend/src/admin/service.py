"""Admin operations: provider gate, trip oversight, payment confirmation."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..auth import models as auth_models
from ..booking.models import Booking
from ..inventory.models import Route, Seat, Trip


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Provider gate
# ---------------------------------------------------------------------------

def list_providers(db: Session, *, status: Optional[str] = None) -> list[dict]:
    q = db.query(auth_models.User).filter(auth_models.User.role == "provider")
    if status:
        q = q.filter(auth_models.User.status == status)
    providers = q.order_by(auth_models.User.created_at.desc()).all()

    out = []
    for p in providers:
        trip_count = db.query(Trip).filter(Trip.provider_id == p.id).count()
        out.append({
            "id": p.id,
            "email": p.email,
            "full_name": p.full_name,
            "phone_number": p.phone_number,
            "status": p.status,
            "email_verified": p.email_verified,
            "created_at": p.created_at,
            "trip_count": trip_count,
            "can_add_trips": p.can_add_trips,
            "can_edit_trips": p.can_edit_trips,
            "can_delete_trips": p.can_delete_trips,
        })
    return out


def _decorate_provider(db: Session, user: auth_models.User) -> dict:
    """Shape a provider row the same way list_providers does — used by the
    approve / block / capability-update handlers so their responses match
    the list response schema exactly."""
    trip_count = db.query(Trip).filter(Trip.provider_id == user.id).count()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "status": user.status,
        "email_verified": user.email_verified,
        "created_at": user.created_at,
        "trip_count": trip_count,
        "can_add_trips": user.can_add_trips,
        "can_edit_trips": user.can_edit_trips,
        "can_delete_trips": user.can_delete_trips,
    }


def update_provider_capabilities(
    db: Session,
    *,
    provider_id: int,
    can_add_trips: Optional[bool] = None,
    can_edit_trips: Optional[bool] = None,
    can_delete_trips: Optional[bool] = None,
) -> auth_models.User:
    """Partial patch on a provider's three trip-management flags. Any field
    left None on the request stays as-is on the row (partial update)."""
    user = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Provider not found")
    changed = {}
    if can_add_trips is not None and can_add_trips != user.can_add_trips:
        changed["can_add_trips"] = can_add_trips
        user.can_add_trips = can_add_trips
    if can_edit_trips is not None and can_edit_trips != user.can_edit_trips:
        changed["can_edit_trips"] = can_edit_trips
        user.can_edit_trips = can_edit_trips
    if can_delete_trips is not None and can_delete_trips != user.can_delete_trips:
        changed["can_delete_trips"] = can_delete_trips
        user.can_delete_trips = can_delete_trips
    if changed:
        db.commit()
        db.refresh(user)
        # Emit one notification per actual change so the provider sees which
        # capabilities flipped (and in what direction).
        from ..notifications import service as notif
        for key, value in changed.items():
            notif.create_notification(
                db,
                user_id=user.id,
                type="provider_capability_changed",
                payload={"capability": key, "value": bool(value)},
            )
    print(
        f"[ADMIN] provider {user.email} capabilities "
        f"add={user.can_add_trips} edit={user.can_edit_trips} delete={user.can_delete_trips}"
    )
    return user


def set_provider_status(db: Session, *, provider_id: int, new_status: str) -> auth_models.User:
    if new_status not in ("pending", "active", "blocked"):
        raise HTTPException(status_code=400, detail="Invalid status")
    user = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Provider not found")
    user.status = new_status
    db.commit()
    db.refresh(user)
    print(f"[ADMIN] provider {user.email} → {new_status}")
    return user


# ---------------------------------------------------------------------------
# Pending payment confirmation (the manual half of what Path A used to do)
# ---------------------------------------------------------------------------

def list_pending_payments(db: Session) -> list[dict]:
    """Bookings sitting in `committed_pending` — waiting for an admin to
    confirm that the cash / bank deposit cleared."""
    rows = (
        db.query(Booking)
        .filter(Booking.status == "committed_pending")
        .order_by(Booking.expires_at.asc())
        .all()
    )

    out = []
    for b in rows:
        trip = db.query(Trip).filter(Trip.id == b.trip_id).first()
        route = db.query(Route).filter(Route.id == trip.route_id).first() if trip else None
        customer = (
            db.query(auth_models.User).filter(auth_models.User.id == b.customer_id).first()
        )
        seat_rows = (
            db.query(Seat).filter(Seat.id.in_(b.seat_ids or [])).all()
            if b.seat_ids
            else []
        )

        out.append({
            "booking_id": b.id,
            "billing_reference": b.billing_reference,
            "customer_email": customer.email if customer else None,
            "customer_name": customer.full_name if customer else None,
            "trip_id": b.trip_id,
            "origin": route.origin if route else "—",
            "destination": route.destination if route else "—",
            "departure_time": trip.departure_time if trip else b.created_at,
            "seats": [s.seat_number for s in seat_rows],
            "total_price": b.total_price,
            "status": b.status,
            "expires_at": b.expires_at,
            "created_at": b.created_at,
        })
    return out


def list_all_bookings(
    db: Session,
    *,
    status: Optional[str] = None,
    q: Optional[str] = None,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    provider_id: Optional[int] = None,
    travel_date: Optional[str] = None,
) -> list[dict]:
    """
    All bookings in the system. Filters:
      - status: exact match (e.g. 'confirmed', 'committed_pending')
      - q:      fuzzy match against customer name, customer email, passenger
                name, billing reference, or booking id
      - origin / destination: ilike match on trip route
      - provider_id: restrict to trips run by a specific operator
      - travel_date: ISO YYYY-MM-DD; restricts to bookings whose trip
                     departs that calendar day
    """
    from datetime import datetime as _dt

    query = db.query(Booking).join(Trip, Trip.id == Booking.trip_id).join(
        Route, Route.id == Trip.route_id
    )
    if status:
        query = query.filter(Booking.status == status)
    if origin:
        query = query.filter(Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(Route.destination.ilike(f"%{destination}%"))
    if provider_id is not None:
        query = query.filter(Trip.provider_id == provider_id)
    if travel_date:
        try:
            day = _dt.fromisoformat(travel_date[:10])
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day.replace(hour=23, minute=59, second=59, microsecond=999_999)
            query = query.filter(Trip.departure_time >= start, Trip.departure_time <= end)
        except ValueError:
            pass  # bad input — treat as no date filter

    rows = query.order_by(Booking.created_at.desc()).all()

    # Post-filter for the fuzzy `q` field, since it spans User + Passenger.
    q_low = q.strip().lower() if q else None

    out = []
    for b in rows:
        trip = db.query(Trip).filter(Trip.id == b.trip_id).first()
        route = db.query(Route).filter(Route.id == trip.route_id).first() if trip else None
        customer = (
            db.query(auth_models.User).filter(auth_models.User.id == b.customer_id).first()
        )
        provider = None
        if trip and trip.provider_id:
            provider = (
                db.query(auth_models.User).filter(auth_models.User.id == trip.provider_id).first()
            )
        seat_rows = (
            db.query(Seat).filter(Seat.id.in_(b.seat_ids or [])).all()
            if b.seat_ids else []
        )
        passenger_names = [p.full_name for p in b.passengers]

        # Apply q filter against the materialized row.
        if q_low:
            haystack = " ".join([
                str(b.id),
                b.billing_reference or "",
                customer.email if customer else "",
                customer.full_name if customer else "",
                *passenger_names,
            ]).lower()
            if q_low not in haystack:
                continue

        out.append({
            "booking_id": b.id,
            "status": b.status,
            "payment_status": b.payment_status,
            "channel": b.channel,
            "billing_reference": b.billing_reference,
            "customer_email": customer.email if customer else None,
            "customer_name": customer.full_name if customer else None,
            "provider_id": trip.provider_id if trip else 0,
            "provider_name": provider.full_name if provider else None,
            "trip_id": b.trip_id,
            "origin": route.origin if route else "—",
            "destination": route.destination if route else "—",
            "departure_time": trip.departure_time if trip else b.created_at,
            "seats": sorted([s.seat_number for s in seat_rows]),
            "passenger_names": passenger_names,
            "total_price": b.total_price,
            "created_at": b.created_at,
        })
    return out


def confirm_payment(
    db: Session,
    *,
    booking_id: int,
    payment_method: str = "admin_confirmed",
) -> tuple[Booking, Optional[str]]:
    """
    Admin manually confirms that payment has cleared. Transitions:
      booking.status         committed_pending → confirmed
      booking.payment_status unpaid            → paid
      seat.status            locked            → booked   (Reaper-immune)

    Returns the booking and the customer's email address (for the simulated
    delivery banner).
    """
    booking = (
        db.query(Booking).filter(Booking.id == booking_id).with_for_update().first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status == "confirmed":
        raise HTTPException(status_code=400, detail="Booking is already confirmed")
    if booking.status not in ("pending", "committed_pending"):
        raise HTTPException(
            status_code=400,
            detail=f"Booking is in a non-confirmable state: {booking.status}",
        )

    # Permanently mark seats as booked (Reaper ignores `booked`)
    if booking.seat_ids:
        db.query(Seat).filter(
            Seat.id.in_(booking.seat_ids), Seat.trip_id == booking.trip_id
        ).update({"status": "booked"}, synchronize_session=False)

    booking.status = "confirmed"
    booking.payment_status = "paid"
    booking.confirmed_at = _now_utc_naive()
    # Always stamp the supplied payment_method on confirmation. A caller-set
    # "cash" (provider walk-in) is more informative than the prior "billing_reference"
    # for accounting / commission downstream.
    booking.payment_method = payment_method
    # Cash walk-ins may have skipped billing intent and lack a reference. Mint
    # one so every confirmed booking has a printable ticket + QR.
    if not booking.billing_reference:
        from ..booking.service import _generate_billing_reference
        booking.billing_reference = _generate_billing_reference()
        booking.bill_generated_at = _now_utc_naive()

    # Commission snapshot — immutable record of (rate_kind, rate_value, rule_id)
    # at the moment of confirmation. Walk-ins short-circuit to 0 inside.
    from ..inventory.models import Trip as _Trip
    from ..finance.service import snapshot_commission
    _trip = db.query(_Trip).filter(_Trip.id == booking.trip_id).first()
    if _trip:
        snapshot_commission(db, booking, _trip)

    db.commit()
    db.refresh(booking)

    customer = (
        db.query(auth_models.User).filter(auth_models.User.id == booking.customer_id).first()
    )
    delivered_to = customer.email if customer else None
    if delivered_to:
        print(f"[EMAIL] ticket confirmation #{booking.id} → {delivered_to}")

    return booking, delivered_to
