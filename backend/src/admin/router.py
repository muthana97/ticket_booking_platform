from datetime import datetime as _dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..auth import models as auth_models
from ..database import get_db
from ..finance import reports as finance_reports
from ..inventory import schemas as inv_schemas
from ..inventory import service as inv_service
from ..audit import service as audit_svc, schemas as audit_schemas
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
def approve_provider(
    provider_id: int, db: Session = Depends(get_db), admin=Depends(require_admin),
):
    """Move a provider from `pending` (or `blocked`) into `active`."""
    user = service.set_provider_status(
        db, provider_id=provider_id, new_status="active", actor_user_id=admin.id,
    )
    return service._decorate_provider(db, user)


@router.post("/providers/{provider_id}/block", response_model=schemas.ProviderSummary)
def block_provider(
    provider_id: int, db: Session = Depends(get_db), admin=Depends(require_admin),
):
    """Block a provider — they can still authenticate but cannot manage trips."""
    user = service.set_provider_status(
        db, provider_id=provider_id, new_status="blocked", actor_user_id=admin.id,
    )
    return service._decorate_provider(db, user)


@router.patch(
    "/providers/{provider_id}/capabilities",
    response_model=schemas.ProviderSummary,
)
def update_provider_capabilities(
    provider_id: int,
    payload: schemas.ProviderCapabilitiesUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Toggle any subset of {can_add_trips, can_edit_trips, can_delete_trips,
    can_view_reports} on a provider. Omitted fields stay as-is."""
    user = service.update_provider_capabilities(
        db,
        provider_id=provider_id,
        can_add_trips=payload.can_add_trips,
        can_edit_trips=payload.can_edit_trips,
        can_delete_trips=payload.can_delete_trips,
        can_view_reports=payload.can_view_reports,
        actor_user_id=admin.id,
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
    travel_date: Optional[str] = Query(default=None, description="ISO date (YYYY-MM-DD) — filters to that calendar day"),
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
    if travel_date:
        try:
            day = _dt.fromisoformat(travel_date[:10])
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day.replace(hour=23, minute=59, second=59, microsecond=999_999)
            query = query.filter(Trip.departure_time >= start, Trip.departure_time <= end)
        except ValueError:
            pass  # bad input — treat as no date filter
    elif time == "upcoming":
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
def admin_delete_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Admin can delete any trip (still refuses if confirmed bookings exist)."""
    from ..inventory.models import Trip as _Trip
    from ..inventory.router import _fanout_trip_delete
    trip = db.query(_Trip).filter(_Trip.id == trip_id).first()
    if trip is not None:
        _fanout_trip_delete(db, trip=trip, actor="admin")
    inv_service.delete_trip(db=db, trip_id=trip_id, actor_user_id=admin.id)
    return None


@router.patch("/trips/{trip_id}", response_model=inv_schemas.TripSearchResponse)
def admin_update_trip(
    trip_id: int,
    payload: inv_schemas.TripUpdateRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Admin can edit any trip's price / departure. No ownership or capability
    gates apply here — admin bypasses both. Past-departure block still holds
    (backend refuses retroactive moves regardless of who's editing)."""
    from ..inventory.router import _fanout_trip_edit
    trip, delta = inv_service.update_trip(
        db=db, trip_id=trip_id,
        price=payload.price, departure_time=payload.departure_time,
        actor_user_id=admin.id,
    )
    _fanout_trip_edit(db, trip=trip, delta=delta, actor="admin", actor_id=None)
    return inv_service.decorate_trip_row(db, trip)


# ---------------------------------------------------------------------------
# Pending payment confirmation
# ---------------------------------------------------------------------------

@router.get("/bookings", response_model=List[schemas.AdminBookingItem])
def list_all_bookings(
    status: Optional[str] = Query(default="confirmed"),
    q: Optional[str] = Query(default=None, description="Fuzzy match on customer / passenger / billing ref / booking id"),
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    provider_id: Optional[int] = Query(default=None),
    travel_date: Optional[str] = Query(default=None, description="ISO date (YYYY-MM-DD) — filters to bookings whose trip departs that day"),
    db: Session = Depends(get_db),
):
    """A-OP-06: All bookings, searchable. Defaults to status='confirmed'."""
    # Treat empty status (or status="any") as no filter
    real_status = None if (status in (None, "", "any")) else status
    return service.list_all_bookings(
        db, status=real_status, q=q, origin=origin, destination=destination,
        provider_id=provider_id, travel_date=travel_date,
    )


@router.get("/payments/pending", response_model=List[schemas.PendingPaymentItem])
def list_pending_payments(db: Session = Depends(get_db)):
    return service.list_pending_payments(db)


@router.post("/payments/{booking_id}/confirm", response_model=schemas.ConfirmPaymentResponse)
def confirm_payment(
    booking_id: int, db: Session = Depends(get_db), admin=Depends(require_admin),
):
    """Move booking from `committed_pending` → `confirmed`, lock seats as
    `booked` permanently, and (in the demo) print a delivery line for the
    confirmation email."""
    booking, delivered_to = service.confirm_payment(
        db, booking_id=booking_id, actor_user_id=admin.id,
    )
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
        d_from, d_to = finance_reports.default_period()
        from_ = from_ or d_from
        to = to or d_to
    finance_reports.validate_period(from_, to)
    return finance_reports.build_reports(
        db, from_str=from_, to_str=to, provider_id=provider_id,
    )


@router.get(
    "/providers/{provider_id}/reports",
    response_model=schemas.ReportsResponse,
)
def provider_reports(
    provider_id: int,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Per-provider drilldown. Thin wrapper that inlines provider_id from
    the URL path and reuses the existing reports aggregation."""
    provider = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not from_ or not to:
        d_from, d_to = finance_reports.default_period()
        from_ = from_ or d_from
        to = to or d_to
    finance_reports.validate_period(from_, to)
    return finance_reports.build_reports(
        db, from_str=from_, to_str=to, provider_id=provider_id,
    )


# ---------------------------------------------------------------------------
# Provider audit log
# ---------------------------------------------------------------------------

@router.get(
    "/providers/{provider_id}/log",
    response_model=audit_schemas.AuditLogResponse,
)
def provider_log(
    provider_id: int,
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    from_: Optional[_dt] = Query(default=None, alias="from"),
    to: Optional[_dt] = None,
    limit: int = 100,
    before_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """Activity log for a single provider. Admin-only in Phase 1;
    Phase 2 will widen for operator-admin scoped to their acts_for_provider_id."""
    provider = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    rows, next_before = audit_svc.query_log(
        db,
        provider_id=provider_id,
        q=q, event_type=event_type,
        from_ts=from_, to_ts=to,
        limit=limit, before_id=before_id,
    )

    # Load actors in one query
    actor_ids = {r.actor_user_id for r in rows}
    actors = {
        u.id: u for u in db.query(auth_models.User).filter(auth_models.User.id.in_(actor_ids)).all()
    }

    items = []
    for r in rows:
        actor = actors.get(r.actor_user_id)
        actor_out = audit_schemas.AuditActor(
            id=r.actor_user_id,
            full_name=actor.full_name if actor else f"user #{r.actor_user_id}",
            role=actor.role if actor else "unknown",
        )
        items.append(audit_schemas.AuditEventItem(
            id=r.id, event_type=r.event_type, actor=actor_out,
            target_type=r.target_type, target_id=r.target_id,
            summary=r.summary, metadata=r.metadata_,
            created_at=r.created_at,
        ))

    return {"items": items, "next_before_id": next_before}
