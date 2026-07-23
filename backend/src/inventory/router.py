from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user, require_active_provider
from ..database import get_db
from . import models, schemas, service

router = APIRouter(prefix="/trips", tags=["Inventory"])


# ---------------------------------------------------------------------------
# Notification fan-out helpers (shared by provider + admin edit / delete paths)
# ---------------------------------------------------------------------------

def _serialize_dt(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _active_customer_ids_for_trip(db, trip_id):
    """Consumer-channel bookings only — walk-ins record the provider's own id
    as customer_id and shouldn't self-notify."""
    from ..booking.models import Booking
    rows = (
        db.query(Booking.id, Booking.customer_id)
        .filter(
            Booking.trip_id == trip_id,
            Booking.status.in_(["pending", "committed_pending", "confirmed"]),
            Booking.channel == "consumer",
        )
        .all()
    )
    return rows  # list of (booking_id, customer_id)


def _fanout_trip_edit(db, *, trip, delta, actor, actor_id):
    """Emit notifications for a trip edit (used by both the provider and the
    admin PATCH paths). `delta` comes from service.update_trip and only
    contains fields that actually changed."""
    if not delta:
        return
    from ..notifications import service as notif
    # 1. Passengers on active bookings — only if departure_time moved.
    if "departure_time" in delta:
        payload_base = {
            "trip_id": trip.id,
            "from": _serialize_dt(delta["departure_time"]["from"]),
            "to": _serialize_dt(delta["departure_time"]["to"]),
        }
        for booking_id, cust_id in _active_customer_ids_for_trip(db, trip.id):
            notif.create_notification(
                db,
                user_id=cust_id,
                type="trip_time_changed",
                payload={**payload_base, "booking_id": booking_id},
            )
    # 2. Counter-party (admin ↔ provider) — for every edit, regardless of field.
    delta_payload = {
        "trip_id": trip.id,
        "changed_fields": list(delta.keys()),
    }
    if "price" in delta:
        delta_payload["price"] = {"from": delta["price"]["from"], "to": delta["price"]["to"]}
    if "departure_time" in delta:
        delta_payload["departure_time"] = {
            "from": _serialize_dt(delta["departure_time"]["from"]),
            "to":   _serialize_dt(delta["departure_time"]["to"]),
        }
    if actor == "provider":
        # Notify every admin. Include the acting provider's display name so
        # the admin console can attribute the edit at a glance without a
        # follow-up lookup.
        from ..auth.models import User
        provider_name = None
        if actor_id:
            provider = db.query(User).filter(User.id == actor_id).first()
            if provider:
                provider_name = provider.full_name
        admin_ids = [row.id for row in db.query(User.id).filter(User.role == "admin").all()]
        notif.create_notifications_bulk(
            db, user_ids=admin_ids, type="trip_edited_by_provider",
            payload={**delta_payload, "provider_id": actor_id, "provider_name": provider_name},
        )
    elif actor == "admin":
        if trip.provider_id:
            notif.create_notification(
                db, user_id=trip.provider_id, type="trip_edited_by_admin",
                payload=delta_payload,
            )


def _fanout_trip_delete(db, *, trip, actor):
    """Emit notifications for a trip deletion. `trip` and its bookings must
    still exist at call time — the delete happens AFTER this returns."""
    from ..notifications import service as notif
    payload = {
        "trip_id": trip.id,
        "origin": trip.route.origin if trip.route else None,
        "destination": trip.route.destination if trip.route else None,
        "departure_time": _serialize_dt(trip.departure_time),
    }
    # Passengers on active bookings — for both provider- and admin-initiated
    # deletes.
    passenger_ids = [
        cust_id for (_bid, cust_id) in _active_customer_ids_for_trip(db, trip.id)
    ]
    notif.create_notifications_bulk(
        db, user_ids=passenger_ids, type="trip_cancelled", payload=payload,
    )
    # Admin-initiated delete → also notify the owning provider.
    if actor == "admin" and trip.provider_id:
        notif.create_notification(
            db, user_id=trip.provider_id, type="trip_deleted_by_admin", payload=payload,
        )


# ---------------------------------------------------------------------------
# Search — open to any authenticated session (customer or provider)
# ---------------------------------------------------------------------------

@router.get("/search", response_model=List[schemas.TripSearchResponse])
def search_trips(
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    travel_date: Optional[datetime] = Query(default=None),
    provider_id: Optional[int] = Query(default=None),
    sort_by: Optional[str] = Query(default="time"),
    db: Session = Depends(get_db),
):
    """
    SRCH-02: Search trips by origin / destination + optional date filter,
    optional operator filter, and sort mode. `sort_by` accepts:
      - "time"       (departure time ascending, the default)
      - "price_asc"  (cheapest first, then time)
      - "price_desc" (most expensive first, then time)
    Any other value falls back to "time".
    """
    query = db.query(models.Trip).join(models.Route)

    if origin:
        query = query.filter(models.Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(models.Route.destination.ilike(f"%{destination}%"))
    if provider_id:
        query = query.filter(models.Trip.provider_id == provider_id)

    if travel_date:
        start = travel_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = travel_date.replace(hour=23, minute=59, second=59, microsecond=0)
        query = query.filter(
            models.Trip.departure_time >= start,
            models.Trip.departure_time <= end,
        )
    else:
        query = query.filter(models.Trip.departure_time >= datetime.utcnow())

    if sort_by == "price_asc":
        query = query.order_by(models.Trip.price.asc(), models.Trip.departure_time.asc())
    elif sort_by == "price_desc":
        query = query.order_by(models.Trip.price.desc(), models.Trip.departure_time.asc())
    else:
        query = query.order_by(models.Trip.departure_time.asc())

    trips = query.all()
    return [service.decorate_trip_row(db, trip) for trip in trips]


@router.get("/providers", response_model=List[dict])
def list_active_providers(db: Session = Depends(get_db)):
    """
    Lightweight roster of active operators, used to populate the customer
    search screen's optional operator filter. Names are already exposed via
    the trip card's "Operated by …" line, so this doesn't leak anything new.
    """
    from ..auth.models import User
    rows = (
        db.query(User.id, User.full_name)
        .filter(User.role == "provider", User.status == "active")
        .order_by(User.full_name.asc())
        .all()
    )
    return [{"id": r[0], "name": r[1]} for r in rows]


# ---------------------------------------------------------------------------
# Provider-only: create / delete trips
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.TripsCreatedResponse, status_code=201)
def create_trip(
    payload: schemas.CreateTripRequest,
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """
    Provider-only. Creates one Trip, or many if `repeat.kind != "once"`.
    Each trip gets its own Bus + Seats, sharing the underlying Route.
    """
    if not provider.can_add_trips:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="Adding trips is disabled for your account. Contact the admin.",
        )
    departures = service.expand_repeat_pattern(
        start=payload.departure_time,
        kind=payload.repeat.kind,
        end_date=payload.repeat.end_date,
        days_of_week=payload.repeat.days_of_week,
    )

    created = []
    for dep in departures:
        trip = service.create_trip(
            db=db,
            origin=payload.origin,
            destination=payload.destination,
            total_seats=payload.total_seats,
            departure_time=dep,
            price=payload.price,
            provider_id=provider.id,
            actor_user_id=provider.id,
        )
        created.append({
            "trip_id": trip.id,
            "origin": payload.origin,
            "destination": payload.destination,
            "departure_time": trip.departure_time,
            "total_seats": payload.total_seats,
            "price": trip.price,
            "message": f"Trip {trip.id} created.",
        })

    return {
        "count": len(created),
        "trips": created,
        "message": (
            f"Created {len(created)} trip(s)."
            if len(created) > 1
            else f"Trip {created[0]['trip_id']} created with {payload.total_seats} seats."
        ),
    }


@router.get("/mine", response_model=List[schemas.TripSearchResponse])
def list_my_trips(
    q: Optional[str] = Query(default=None),
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    time: Optional[str] = Query(default=None, regex="^(upcoming|past|all)$"),
    travel_date: Optional[str] = Query(default=None, description="ISO date (YYYY-MM-DD) — filters to that calendar day"),
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """Provider's own trips only — enforces data isolation between providers.
    Same filter shape as /admin/trips for consistency in the UI."""
    from datetime import datetime as _dt
    query = db.query(models.Trip).join(models.Route).filter(
        models.Trip.provider_id == provider.id
    )
    if origin:
        query = query.filter(models.Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(models.Route.destination.ilike(f"%{destination}%"))
    if travel_date:
        try:
            day = _dt.fromisoformat(travel_date[:10])
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = day.replace(hour=23, minute=59, second=59, microsecond=999_999)
            query = query.filter(models.Trip.departure_time >= start, models.Trip.departure_time <= end)
        except ValueError:
            pass  # bad input — treat as no date filter
    elif time == "upcoming":
        query = query.filter(models.Trip.departure_time >= _dt.utcnow())
    elif time == "past":
        query = query.filter(models.Trip.departure_time < _dt.utcnow())
    elif time is None:
        # Default: upcoming only. UI dropped its explicit picker so this
        # matches what admins + operators see when they open the tab.
        query = query.filter(models.Trip.departure_time >= _dt.utcnow())
    trips = query.order_by(models.Trip.departure_time.asc()).all()

    if q:
        q_low = q.strip().lower()
        trips = [
            t for t in trips
            if q_low in " ".join([str(t.id), t.route.origin, t.route.destination]).lower()
        ]

    return [service.decorate_trip_row(db, trip) for trip in trips]


@router.patch("/{trip_id}", response_model=schemas.TripSearchResponse)
def update_trip(
    trip_id: int,
    payload: schemas.TripUpdateRequest,
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """Provider-only. Update price and/or departure time on one of their own
    trips. Ownership + can_edit_trips capability + past-departure block all
    apply. Existing bookings keep their locked-in price."""
    from fastapi import HTTPException
    if not provider.can_edit_trips:
        raise HTTPException(
            status_code=403,
            detail="Editing trips is disabled for your account. Contact the admin.",
        )
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.provider_id != provider.id:
        raise HTTPException(
            status_code=403,
            detail="You can only edit trips you own.",
        )
    trip, delta = service.update_trip(
        db=db, trip_id=trip_id,
        price=payload.price, departure_time=payload.departure_time,
        actor_user_id=provider.id,
    )
    _fanout_trip_edit(db, trip=trip, delta=delta, actor="provider", actor_id=provider.id)
    return service.decorate_trip_row(db, trip)


@router.delete("/{trip_id}", status_code=204)
def delete_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """
    Provider-only. RBAC: refuses if the trip belongs to another provider
    (provider data isolation). Also refuses if any confirmed booking exists.
    """
    from fastapi import HTTPException
    if not provider.can_delete_trips:
        raise HTTPException(
            status_code=403,
            detail="Deleting trips is disabled for your account. Contact the admin.",
        )
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.provider_id != provider.id:
        raise HTTPException(
            status_code=403,
            detail="You can only delete trips you own.",
        )
    _fanout_trip_delete(db, trip=trip, actor="provider")
    service.delete_trip(db=db, trip_id=trip_id, actor_user_id=provider.id)
    return None


# ---------------------------------------------------------------------------
# Per-trip seat-map placeholder (still in use for legacy calls)
# ---------------------------------------------------------------------------

@router.get("/{trip_id}/seats")
def get_trip_seat_map(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """For real-time updates use /bookings/trips/{trip_id}/seats/stream."""
    seats = db.query(models.Seat).filter(models.Seat.trip_id == trip_id).all()
    return [{"seat_number": s.seat_number, "status": s.status} for s in seats]
