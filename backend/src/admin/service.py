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
        })
    return out


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
) -> list[dict]:
    """
    All bookings in the system. Filters:
      - status: exact match (e.g. 'confirmed', 'committed_pending')
      - q:      fuzzy match against customer name, customer email, passenger
                name, billing reference, or booking id
      - origin / destination: ilike match on trip route
    """
    query = db.query(Booking).join(Trip, Trip.id == Booking.trip_id).join(
        Route, Route.id == Trip.route_id
    )
    if status:
        query = query.filter(Booking.status == status)
    if origin:
        query = query.filter(Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(Route.destination.ilike(f"%{destination}%"))

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
    # Always stamp the supplied payment_method on confirmation. A caller-set
    # "cash" (provider walk-in) is more informative than the prior "billing_reference"
    # for accounting / commission downstream.
    booking.payment_method = payment_method

    db.commit()
    db.refresh(booking)

    customer = (
        db.query(auth_models.User).filter(auth_models.User.id == booking.customer_id).first()
    )
    delivered_to = customer.email if customer else None
    if delivered_to:
        print(f"[EMAIL] ticket confirmation #{booking.id} → {delivered_to}")

    return booking, delivered_to
