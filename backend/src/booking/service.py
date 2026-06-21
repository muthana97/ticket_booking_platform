import random
import string
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Booking, Passenger
from ..auth.models import User
from ..inventory.models import Seat, Trip, Route


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _now_utc_naive() -> datetime:
    """Naive UTC — matches the timestamp convention used across this project."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_billing_reference() -> str:
    """Deterministically-structured mock ref code: BOK-NNNN-NN."""
    body = "".join(random.choices(string.digits, k=4))
    suffix = "".join(random.choices(string.digits, k=2))
    return f"BOK-{body}-{suffix}"


# ---------------------------------------------------------------------------
# The Shared Locking Core (SEAT-02 / SEAT-04)
# Both consumer checkout AND provider walk-in flow through this function.
# ---------------------------------------------------------------------------

def lock_seats(
    db: Session,
    trip_id: int,
    seat_numbers: list[str],
    customer_id: int,
    total_price: float,
    passengers: list | None = None,
    channel: str = "consumer",
):
    """
    Atomically lock seats using `with_for_update` row-level locks, then create
    the corresponding 'pending' Booking record with a 10-minute hold window.

    The Reaper background daemon (tasks.py) reads `expires_at` to release
    seats from any booking whose window lapses without billing intent.
    """
    # 1. Row-level lock on the requested seats
    seats = (
        db.query(Seat)
        .filter(Seat.trip_id == trip_id, Seat.seat_number.in_(seat_numbers))
        .with_for_update()
        .all()
    )

    # 2. Validate availability under the lock
    if len(seats) != len(seat_numbers):
        raise HTTPException(status_code=404, detail="One or more seats not found")
    for seat in seats:
        if seat.status != "available":
            raise HTTPException(
                status_code=400,
                detail=f"Seat {seat.seat_number} is already taken",
            )

    # 3. Flip seats → locked
    for seat in seats:
        seat.status = "locked"

    # 4. Create the Booking record (10-minute hold window)
    now = _now_utc_naive()
    new_booking = Booking(
        customer_id=customer_id,
        trip_id=trip_id,
        status="pending",
        total_price=total_price,
        channel=channel,
        payment_status="unpaid",
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        seat_ids=[seat.id for seat in seats],
    )
    db.add(new_booking)
    db.flush()  # Need new_booking.id for passenger FKs

    # 5. Attach passengers (if provided)
    if passengers:
        for p in passengers:
            db.add(
                Passenger(
                    booking_id=new_booking.id,
                    full_name=p.full_name,
                    phone_number=p.phone_number,
                    national_id=p.national_id,
                    seat_number=p.seat_number,
                )
            )

    db.commit()
    db.refresh(new_booking)
    return {"booking": new_booking, "seats": seats}


# ---------------------------------------------------------------------------
# Billing Intent (Path B) — produces the stakeholder Ticket
# Path A (direct payment settlement) is deferred to V2 per CLAUDE.md.
# ---------------------------------------------------------------------------

def create_billing_intent(db: Session, booking_id: int, customer_id: int | None = None):
    """
    Transition booking 'pending' → 'committed_pending', mint a billing reference,
    extend the hold window to 30 minutes, and return a rich Ticket payload.

    `customer_id=None` allows provider walk-ins (where there is no JWT customer)
    to settle to billing reference via the same code path.
    """
    # 1. Row-lock the booking for safe state transition
    q = db.query(Booking).filter(Booking.id == booking_id)
    if customer_id is not None:
        q = q.filter(Booking.customer_id == customer_id)
    booking = q.with_for_update().first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking record not found")

    now = _now_utc_naive()
    if booking.expires_at < now:
        raise HTTPException(status_code=400, detail="Booking hold window has expired")
    if booking.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Booking is in an invalid state for billing intent: {booking.status}",
        )

    # 2. Advance state + mint reference + extend window to 30 min
    booking.status = "committed_pending"
    booking.payment_method = "billing_reference"
    booking.billing_reference = _generate_billing_reference()
    booking.bill_generated_at = now
    booking.expires_at = now + timedelta(minutes=30)

    db.commit()
    db.refresh(booking)
    return booking


def build_ticket_payload(db: Session, booking: Booking) -> dict:
    """
    Compose the stakeholder Ticket JSON: booking, trip, passengers, seats,
    billing ref — everything needed to render a printable receipt without
    further round-trips.
    """
    trip = db.query(Trip).filter(Trip.id == booking.trip_id).first()
    route = db.query(Route).filter(Route.id == trip.route_id).first() if trip else None

    # Resolve seat numbers from the JSON-tracked ids
    seat_rows = (
        db.query(Seat).filter(Seat.id.in_(booking.seat_ids or [])).all()
        if booking.seat_ids
        else []
    )
    seat_numbers = [s.seat_number for s in seat_rows]

    passengers = [
        {
            "full_name": p.full_name,
            "seat_number": p.seat_number,
            "phone_number": p.phone_number,
        }
        for p in booking.passengers
    ]

    trip_summary = {
        "trip_id": trip.id if trip else booking.trip_id,
        "origin": route.origin if route else "—",
        "destination": route.destination if route else "—",
        "departure_time": trip.departure_time if trip else booking.created_at,
        "duration": route.duration if route else None,
        "price_per_seat": trip.price if trip else 0.0,
    }

    # Simulated email delivery: look up the booking owner's address and log it.
    customer = (
        db.query(User).filter(User.id == booking.customer_id).first()
    )
    delivered_to = customer.email if customer else None
    if delivered_to:
        print(
            f"[EMAIL] ticket #{booking.id} ({booking.billing_reference}) → {delivered_to}"
        )

    # Compact QR payload — pipe-delimited so a scanner can split without JSON.
    # Format: TAZ|<booking_id>|<billing_ref>|<seats csv>|<departure ISO>|<status>
    qr_payload = (
        "TAZ|"
        f"{booking.id}|"
        f"{booking.billing_reference or ''}|"
        f"{','.join(seat_numbers)}|"
        f"{(trip.departure_time.isoformat() if trip else '')}|"
        f"{booking.status}"
    )

    return {
        "booking_id": booking.id,
        "booking_status": booking.status,
        "payment_status": booking.payment_status,
        "payment_method": booking.payment_method,
        "billing_reference": booking.billing_reference,
        "bill_generated_at": booking.bill_generated_at,
        "expires_at": booking.expires_at,
        "trip": trip_summary,
        "passengers": passengers,
        "seats": seat_numbers,
        "total_price": booking.total_price,
        "delivered_to": delivered_to,
        "qr_payload": qr_payload,
        "message": (
            f"Ticket #{booking.id} generated. "
            + (f"Sent to {delivered_to}. " if delivered_to else "")
            + f"Settle reference {booking.billing_reference} within 30 minutes."
        ),
    }


# ---------------------------------------------------------------------------
# Customer / Provider booking lists (My Tickets / Provider Bookings)
# ---------------------------------------------------------------------------

def list_user_bookings(db: Session, *, user_id: int) -> list[dict]:
    """
    Return all consumer-channel bookings owned by this user, decorated with
    trip details and a precomputed `is_past` flag. Walk-in bookings (where
    customer_id happens to be a provider's user id) are filtered out.
    """
    rows = (
        db.query(Booking)
        .filter(Booking.customer_id == user_id, Booking.channel == "consumer")
        .order_by(Booking.created_at.desc())
        .all()
    )
    return [_decorate_booking_row(db, b) for b in rows]


def list_provider_bookings(db: Session, *, provider_id: int) -> list[dict]:
    """
    Every booking on trips owned by this provider — both consumer and walk-in.
    Joined to Trip so the response carries trip + route info inline.
    """
    rows = (
        db.query(Booking)
        .join(Trip, Trip.id == Booking.trip_id)
        .filter(Trip.provider_id == provider_id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    out = []
    for b in rows:
        trip = db.query(Trip).filter(Trip.id == b.trip_id).first()
        route = db.query(Route).filter(Route.id == trip.route_id).first() if trip else None
        seat_rows = (
            db.query(Seat).filter(Seat.id.in_(b.seat_ids or [])).all()
            if b.seat_ids else []
        )
        customer = db.query(User).filter(User.id == b.customer_id).first()
        out.append({
            "booking_id": b.id,
            "status": b.status,
            "payment_status": b.payment_status,
            "channel": b.channel,
            "billing_reference": b.billing_reference,
            "trip_id": b.trip_id,
            "origin": route.origin if route else "—",
            "destination": route.destination if route else "—",
            "departure_time": trip.departure_time if trip else b.created_at,
            "seats": sorted([s.seat_number for s in seat_rows], key=_seat_sort_key),
            "passenger_count": len(b.passengers),
            "total_price": b.total_price,
            "created_at": b.created_at,
            "customer_email": customer.email if customer else None,
            "customer_name": customer.full_name if customer else None,
            "commission_amount": b.commission_amount,
            "net_amount": (
                round(b.total_price - b.commission_amount, 2)
                if b.commission_amount is not None and b.total_price is not None
                else None
            ),
        })
    return out


def _decorate_booking_row(db: Session, booking: Booking) -> dict:
    """Shared row decorator for customer's 'My Tickets'."""
    trip = db.query(Trip).filter(Trip.id == booking.trip_id).first()
    route = db.query(Route).filter(Route.id == trip.route_id).first() if trip else None
    seat_rows = (
        db.query(Seat).filter(Seat.id.in_(booking.seat_ids or [])).all()
        if booking.seat_ids else []
    )
    is_past = bool(trip and trip.departure_time < _now_utc_naive())
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "channel": booking.channel,
        "billing_reference": booking.billing_reference,
        "trip_id": booking.trip_id,
        "origin": route.origin if route else "—",
        "destination": route.destination if route else "—",
        "departure_time": trip.departure_time if trip else booking.created_at,
        "seats": sorted([s.seat_number for s in seat_rows], key=_seat_sort_key),
        "total_price": booking.total_price,
        "created_at": booking.created_at,
        "expires_at": booking.expires_at,
        "is_past": is_past,
    }


def _seat_sort_key(s: str) -> str:
    # F1/F2/F3 first, then numeric row + letter — keeps display stable.
    if s.startswith("F"):
        return "0_" + s
    import re
    m = re.match(r"^(\d+)([A-Z])$", s)
    if not m:
        return "9_" + s
    return "1_" + m.group(1).zfill(3) + m.group(2)


# ---------------------------------------------------------------------------
# Real-time seat state (powers /seats/stream long-polling)
# ---------------------------------------------------------------------------

def get_seat_state_snapshot(db: Session, trip_id: int) -> dict:
    """
    Cheap snapshot of the seat matrix for a trip. The 'version' is a hash-like
    rollup of (id,status) pairs — changes whenever any seat flips state.
    """
    seats = (
        db.query(Seat)
        .filter(Seat.trip_id == trip_id)
        .order_by(Seat.id.asc())
        .all()
    )
    if not seats:
        # Surface 404 so the streaming endpoint can respond cleanly
        raise HTTPException(status_code=404, detail="Trip has no seats")

    # Tally
    available = sum(1 for s in seats if s.status == "available")
    locked = sum(1 for s in seats if s.status == "locked")
    booked = sum(1 for s in seats if s.status == "booked")

    # Monotonic-ish version: order-stable hash of (id, status) pairs
    status_code = {"available": 0, "locked": 1, "booked": 2}
    version = 0
    for s in seats:
        version = (version * 7) + (s.id * 3 + status_code.get(s.status, 0))
        version &= 0xFFFFFFFF  # keep it 32-bit for JSON friendliness

    return {
        "trip_id": trip_id,
        "version": version,
        "total_seats": len(seats),
        "available": available,
        "locked": locked,
        "booked": booked,
        "seats": [
            {"seat_number": s.seat_number, "status": s.status} for s in seats
        ],
        "fetched_at": _now_utc_naive(),
    }


# ---------------------------------------------------------------------------
# Operational manifest (MAN-02)
# ---------------------------------------------------------------------------

def compile_trip_manifest(db: Session, trip_id: int) -> dict:
    """Passenger manifest for a trip — only 'confirmed' bookings counted."""
    confirmed = (
        db.query(Booking)
        .filter(Booking.trip_id == trip_id, Booking.status == "confirmed")
        .all()
    )

    manifest_list = []
    for booking in confirmed:
        for p in booking.passengers:
            manifest_list.append(
                {
                    "passenger_id": p.id,
                    "full_name": p.full_name,
                    "phone_number": p.phone_number,
                    "national_id": p.national_id,
                    "seat_number": p.seat_number,
                    "booking_id": booking.id,
                }
            )

    return {
        "trip_id": trip_id,
        "total_confirmed_passengers": len(manifest_list),
        "generated_at": _now_utc_naive(),
        "manifest": manifest_list,
    }
