import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user, require_active_provider
from ..auth.models import User
from ..database import get_db, SessionLocal
from ..inventory.models import Trip
from . import schemas, service
from .models import Booking

router = APIRouter(prefix="/bookings", tags=["Bookings"])


# ---------------------------------------------------------------------------
# Consumer checkout — atomic lock + pending booking
# ---------------------------------------------------------------------------

@router.post("/lock", response_model=schemas.BookingResponse)
def reserve_seats(
    payload: schemas.BookingLockRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    SEAT-04: Consumer seat lock. Routes through the shared `lock_seats`
    atomic transaction. Creates a 'pending' booking with a 10-minute hold.
    """
    result = service.lock_seats(
        db=db,
        trip_id=payload.trip_id,
        seat_numbers=payload.seat_numbers,
        customer_id=current_user.id,
        total_price=payload.total_price,
        passengers=payload.passengers,
        channel="consumer",
    )

    booking = result["booking"]
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "channel": booking.channel,
        "payment_status": booking.payment_status,
        "total_price": booking.total_price,
        "expires_at": booking.expires_at,
        "seats": [s.seat_number for s in result["seats"]],
        "message": f"Seats locked for {current_user.email}.",
    }


# ---------------------------------------------------------------------------
# Provider walk-in — SAME atomic core, scoped to provider's own trips
# ---------------------------------------------------------------------------

@router.post("/walkin", response_model=schemas.BookingResponse)
def reserve_seats_walkin(
    payload: schemas.WalkInBookingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_provider),
):
    """
    Provider Walk-In booking. RBAC: caller must be an active provider AND
    must own the target trip. A provider cannot walk-in seats on another
    provider's trip.
    """
    trip = db.query(Trip).filter(Trip.id == payload.trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.provider_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only book seats on trips you own.",
        )

    result = service.lock_seats(
        db=db,
        trip_id=payload.trip_id,
        seat_numbers=payload.seat_numbers,
        customer_id=current_user.id,
        total_price=payload.total_price,
        passengers=payload.passengers,
        channel="walkin",
    )

    booking = result["booking"]
    return {
        "booking_id": booking.id,
        "status": booking.status,
        "channel": booking.channel,
        "payment_status": booking.payment_status,
        "total_price": booking.total_price,
        "expires_at": booking.expires_at,
        "seats": [s.seat_number for s in result["seats"]],
        "message": f"Walk-in seats locked by {current_user.email}.",
    }


# ---------------------------------------------------------------------------
# Billing Intent (Path B) — produces the stakeholder Ticket
# ---------------------------------------------------------------------------

@router.post("/intent/billing", response_model=schemas.TicketResponse)
def commit_billing_intent(
    payload: schemas.BillingIntentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    PAY-04 (Path B): Mint a billing reference, extend the hold to 30 minutes,
    and return the complete printable Ticket payload.
    """
    booking = service.create_billing_intent(
        db=db,
        booking_id=payload.booking_id,
        customer_id=current_user.id,
    )
    return service.build_ticket_payload(db=db, booking=booking)


# ---------------------------------------------------------------------------
# Ticket re-fetch — for "My Tickets" re-open without state mutation
# ---------------------------------------------------------------------------

@router.get("/{booking_id}/ticket", response_model=schemas.TicketResponse)
def get_ticket(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the Ticket payload for an existing booking without mutating state.
    Used by the customer's 'My Tickets' view to re-open a previously-issued
    ticket without minting a new billing reference.

    Access rules:
      - Booking owner (customer_id) can always read their own ticket.
      - Admins can read any ticket.
      - Providers can read tickets on trips they own.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    is_owner = booking.customer_id == current_user.id
    is_admin = current_user.role == "admin"
    is_trip_owner = False
    if current_user.role == "provider":
        trip = db.query(Trip).filter(Trip.id == booking.trip_id).first()
        is_trip_owner = bool(trip and trip.provider_id == current_user.id)

    if not (is_owner or is_admin or is_trip_owner):
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket")

    if not booking.billing_reference:
        raise HTTPException(
            status_code=400,
            detail="Ticket not yet issued for this booking (still in initial hold).",
        )

    return service.build_ticket_payload(db=db, booking=booking)


# ---------------------------------------------------------------------------
# Customer "My Tickets" — consumer-channel bookings owned by the caller
# ---------------------------------------------------------------------------

@router.get("/me", response_model=list[schemas.MyBookingItem])
def list_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    TKT-01/02: All bookings owned by the current customer (channel=consumer
    only). Frontend buckets these by status + departure-time.
    """
    return service.list_user_bookings(db=db, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Provider walk-in payment confirmation (P-PAY-03 — cash is confirmed
# immediately, no admin round-trip)
# ---------------------------------------------------------------------------

@router.post("/{booking_id}/provider-confirm")
def provider_confirm_walkin(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_provider),
):
    """
    Provider-only. Marks a walk-in booking as paid in one shot:
      status   pending|committed_pending → confirmed
      payment  unpaid                    → paid (method='cash')
      seats    locked                    → booked (Reaper-immune)

    Restricted to:
      - bookings on trips owned by the calling provider
      - channel='walkin' (consumer bookings still flow through Path B / admin)
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.channel != "walkin":
        raise HTTPException(
            status_code=400,
            detail="Provider confirmation is only available for walk-in bookings.",
        )

    trip = db.query(Trip).filter(Trip.id == booking.trip_id).first()
    if not trip or trip.provider_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only confirm bookings on your own trips.",
        )

    # Reuse the admin confirmation helper — the seat-state + booking-status
    # transition is identical; only the payment_method differs.
    from ..admin.service import confirm_payment
    booking, delivered_to = confirm_payment(
        db, booking_id=booking_id, payment_method="cash"
    )

    return {
        "booking_id": booking.id,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "payment_method": booking.payment_method,
        "delivered_to": delivered_to,
        "message": f"Walk-in booking #{booking.id} confirmed (cash).",
    }


# ---------------------------------------------------------------------------
# Provider "My Bookings" — every booking on trips owned by this provider
# ---------------------------------------------------------------------------

@router.get("/provider/mine", response_model=list[schemas.ProviderBookingItem])
def list_provider_bookings(
    q: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    destination: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_provider),
):
    """P-EXT-04 / P-EXT-05: bookings on this provider's trips (both channels).
    Filter params parallel /admin/bookings."""
    rows = service.list_provider_bookings(db=db, provider_id=current_user.id)
    # Filter in Python — the result set is small per provider.
    if status and status != "any":
        rows = [r for r in rows if r["status"] == status]
    if origin:
        o = origin.lower(); rows = [r for r in rows if o in r["origin"].lower()]
    if destination:
        d = destination.lower(); rows = [r for r in rows if d in r["destination"].lower()]
    if q:
        q_low = q.strip().lower()
        rows = [
            r for r in rows
            if q_low in " ".join([
                str(r["booking_id"]),
                r.get("billing_reference") or "",
                r.get("customer_name") or "",
                r.get("customer_email") or "",
                r["origin"], r["destination"],
            ]).lower()
        ]
    return rows


# ---------------------------------------------------------------------------
# Real-time seat state — HTTP long-polling
# ---------------------------------------------------------------------------

@router.get("/trips/{trip_id}/seats/stream", response_model=schemas.SeatStateSnapshot)
async def stream_seat_state(
    trip_id: int,
    since: int | None = Query(
        default=None,
        description="Last-seen version. If state has changed, returns immediately; "
                    "otherwise holds open up to ~10s waiting for a change.",
    ),
    timeout_seconds: float = Query(default=10.0, ge=0.5, le=25.0),
):
    """Long-polling seat-state stream (SEAT-03 / NFR-04)."""
    poll_interval = 0.5
    elapsed = 0.0

    def _snapshot() -> dict:
        db = SessionLocal()
        try:
            return service.get_seat_state_snapshot(db=db, trip_id=trip_id)
        finally:
            db.close()

    snapshot = _snapshot()
    if since is None or snapshot["version"] != since:
        return snapshot

    while elapsed < timeout_seconds:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        snapshot = _snapshot()
        if snapshot["version"] != since:
            return snapshot

    return snapshot


# ---------------------------------------------------------------------------
# Operational manifest (MAN-02)
# ---------------------------------------------------------------------------

@router.get(
    "/trips/{trip_id}/manifest",
    response_model=schemas.TripManifestResponse,
)
def get_trip_manifest(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MAN-02: Structured passenger manifest for an operational trip."""
    return service.compile_trip_manifest(db=db, trip_id=trip_id)
