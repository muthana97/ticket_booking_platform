import re
from datetime import datetime as _dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from ..finance import reports as finance_reports
from ..inventory import schemas as inv_schemas
from ..inventory import service as inv_service
from . import schemas, service

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


_YYYY_MM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_period(from_str: str, to_str: str) -> None:
    if not _YYYY_MM.match(from_str) or not _YYYY_MM.match(to_str):
        raise HTTPException(400, "from/to must be in YYYY-MM format")
    fy, fm = map(int, from_str.split("-"))
    ty, tm = map(int, to_str.split("-"))
    if (fy, fm) > (ty, tm):
        raise HTTPException(400, "from must be <= to")
    months = (ty - fy) * 12 + (tm - fm) + 1
    if months > 24:
        raise HTTPException(400, "Date range cannot exceed 24 months")


def _default_period() -> tuple[str, str]:
    now = _dt.utcnow()
    # 5 months ago through current → 6-month inclusive window
    m = now.month - 5
    y = now.year
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}", f"{now.year:04d}-{now.month:02d}"


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
    return service._decorate_provider(db, user)


@router.post("/providers/{provider_id}/block", response_model=schemas.ProviderSummary)
def block_provider(provider_id: int, db: Session = Depends(get_db)):
    """Block a provider — they can still authenticate but cannot manage trips."""
    user = service.set_provider_status(db, provider_id=provider_id, new_status="blocked")
    return service._decorate_provider(db, user)


@router.patch(
    "/providers/{provider_id}/capabilities",
    response_model=schemas.ProviderSummary,
)
def update_provider_capabilities(
    provider_id: int,
    payload: schemas.ProviderCapabilitiesUpdate,
    db: Session = Depends(get_db),
):
    """Toggle any subset of {can_add_trips, can_edit_trips, can_delete_trips}
    on a provider. Omitted fields stay as-is."""
    user = service.update_provider_capabilities(
        db,
        provider_id=provider_id,
        can_add_trips=payload.can_add_trips,
        can_edit_trips=payload.can_edit_trips,
        can_delete_trips=payload.can_delete_trips,
    )
    return service._decorate_provider(db, user)


# ---------------------------------------------------------------------------
# Trip oversight (admin can view & delete any provider's trips)
# ---------------------------------------------------------------------------

@router.get("/trips", response_model=List[inv_schemas.TripSearchResponse])
def list_trips(
    provider_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Fuzzy match on origin, destination, provider name, trip id"),
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    time: Optional[str] = Query(default=None, regex="^(upcoming|past|all)$"),
    db: Session = Depends(get_db),
):
    """All trips in the system. Filters mirror /admin/bookings for parity."""
    from datetime import datetime as _dt

    from ..auth.models import User as _User
    from ..inventory.models import Route, Trip

    query = db.query(Trip).join(Route, Route.id == Trip.route_id)
    if provider_id is not None:
        query = query.filter(Trip.provider_id == provider_id)
    if origin:
        query = query.filter(Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(Route.destination.ilike(f"%{destination}%"))
    if time == "upcoming":
        query = query.filter(Trip.departure_time >= _dt.utcnow())
    elif time == "past":
        query = query.filter(Trip.departure_time < _dt.utcnow())
    # time == "all" or None → no temporal filter

    trips = query.order_by(Trip.departure_time.asc()).all()

    # Fuzzy `q` against the decorated row (includes provider name) — applied
    # in Python since it spans Route + User.
    if q:
        q_low = q.strip().lower()
        rows = []
        for trip in trips:
            provider = (
                db.query(_User).filter(_User.id == trip.provider_id).first()
                if trip.provider_id else None
            )
            haystack = " ".join([
                str(trip.id),
                trip.route.origin,
                trip.route.destination,
                provider.full_name if provider else "",
            ]).lower()
            if q_low in haystack:
                rows.append(trip)
        trips = rows

    return [inv_service.decorate_trip_row(db, trip) for trip in trips]


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


# ---------------------------------------------------------------------------
# Reports (financial + operational, monthly by confirmation date)
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=schemas.ReportsResponse)
def get_reports(
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    provider_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    if not from_ or not to:
        d_from, d_to = _default_period()
        from_ = from_ or d_from
        to = to or d_to
    _validate_period(from_, to)
    return finance_reports.build_reports(
        db, from_str=from_, to_str=to, provider_id=provider_id,
    )
