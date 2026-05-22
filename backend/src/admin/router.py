from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from ..inventory import schemas as inv_schemas
from ..inventory import service as inv_service
from . import schemas, service

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------------------
# Provider gate
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=List[schemas.ProviderSummary])
def list_providers(
    status: Optional[str] = Query(default=None, regex="^(pending|active|blocked)$"),
    db: Session = Depends(get_db),
):
    """List provider users, optionally filtered by status."""
    return service.list_providers(db, status=status)


@router.post("/providers/{provider_id}/approve", response_model=schemas.ProviderSummary)
def approve_provider(provider_id: int, db: Session = Depends(get_db)):
    """Move a provider from `pending` (or `blocked`) into `active`."""
    user = service.set_provider_status(db, provider_id=provider_id, new_status="active")
    trip_count = 0  # fresh approvals have no trips yet by definition
    from ..inventory.models import Trip as _Trip
    trip_count = db.query(_Trip).filter(_Trip.provider_id == user.id).count()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "status": user.status,
        "email_verified": user.email_verified,
        "created_at": user.created_at,
        "trip_count": trip_count,
    }


@router.post("/providers/{provider_id}/block", response_model=schemas.ProviderSummary)
def block_provider(provider_id: int, db: Session = Depends(get_db)):
    """Block a provider — they can still authenticate but cannot manage trips."""
    user = service.set_provider_status(db, provider_id=provider_id, new_status="blocked")
    from ..inventory.models import Trip as _Trip
    trip_count = db.query(_Trip).filter(_Trip.provider_id == user.id).count()
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone_number": user.phone_number,
        "status": user.status,
        "email_verified": user.email_verified,
        "created_at": user.created_at,
        "trip_count": trip_count,
    }


# ---------------------------------------------------------------------------
# Trip oversight (admin can view & delete any provider's trips)
# ---------------------------------------------------------------------------

@router.get("/trips", response_model=List[inv_schemas.TripSearchResponse])
def list_trips(
    provider_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """All trips in the system, optionally scoped to a single provider."""
    from ..inventory.models import Seat, Trip
    q = db.query(Trip)
    if provider_id is not None:
        q = q.filter(Trip.provider_id == provider_id)
    trips = q.order_by(Trip.departure_time.asc()).all()

    out = []
    for trip in trips:
        available = (
            db.query(Seat)
            .filter(Seat.trip_id == trip.id, Seat.status == "available")
            .count()
        )
        total = db.query(Seat).filter(Seat.trip_id == trip.id).count()
        out.append({
            "trip_id": trip.id,
            "provider_id": trip.provider_id or 0,
            "origin": trip.route.origin,
            "destination": trip.route.destination,
            "departure_time": trip.departure_time,
            "duration": trip.route.duration,
            "price": trip.price,
            "total_seats": total,
            "available_seats_count": available,
        })
    return out


@router.delete("/trips/{trip_id}", status_code=204)
def admin_delete_trip(trip_id: int, db: Session = Depends(get_db)):
    """Admin can delete any trip (still refuses if confirmed bookings exist)."""
    inv_service.delete_trip(db=db, trip_id=trip_id)
    return None


# ---------------------------------------------------------------------------
# Pending payment confirmation
# ---------------------------------------------------------------------------

@router.get("/bookings", response_model=List[schemas.AdminBookingItem])
def list_all_bookings(
    status: Optional[str] = Query(default="confirmed"),
    q: Optional[str] = Query(default=None, description="Fuzzy match on customer / passenger / billing ref / booking id"),
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """A-OP-06: All bookings, searchable. Defaults to status='confirmed'."""
    # Treat empty status (or status="any") as no filter
    real_status = None if (status in (None, "", "any")) else status
    return service.list_all_bookings(
        db, status=real_status, q=q, origin=origin, destination=destination
    )


@router.get("/payments/pending", response_model=List[schemas.PendingPaymentItem])
def list_pending_payments(db: Session = Depends(get_db)):
    return service.list_pending_payments(db)


@router.post("/payments/{booking_id}/confirm", response_model=schemas.ConfirmPaymentResponse)
def confirm_payment(booking_id: int, db: Session = Depends(get_db)):
    """Move booking from `committed_pending` → `confirmed`, lock seats as
    `booked` permanently, and (in the demo) print a delivery line for the
    confirmation email."""
    booking, delivered_to = service.confirm_payment(db, booking_id=booking_id)
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "delivered_to": delivered_to,
        "message": (
            f"Booking #{booking.id} confirmed. Seats locked permanently. "
            + (f"Confirmation emailed to {delivered_to}." if delivered_to else "")
        ),
    }
