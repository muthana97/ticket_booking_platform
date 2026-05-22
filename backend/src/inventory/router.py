from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user, require_active_provider
from ..database import get_db
from . import models, schemas, service

router = APIRouter(prefix="/trips", tags=["Inventory"])


# ---------------------------------------------------------------------------
# Search — open to any authenticated session (customer or provider)
# ---------------------------------------------------------------------------

@router.get("/search", response_model=List[schemas.TripSearchResponse])
def search_trips(
    origin: Optional[str] = Query(default=None),
    destination: Optional[str] = Query(default=None),
    travel_date: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    SRCH-02: Search trips by origin / destination. `travel_date` is optional —
    omit to see every future trip on the route. With no filters at all,
    returns all future trips (useful for the provider dashboard).
    """
    query = db.query(models.Trip).join(models.Route)

    if origin:
        query = query.filter(models.Route.origin.ilike(f"%{origin}%"))
    if destination:
        query = query.filter(models.Route.destination.ilike(f"%{destination}%"))

    if travel_date:
        start = travel_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = travel_date.replace(hour=23, minute=59, second=59, microsecond=0)
        query = query.filter(
            models.Trip.departure_time >= start,
            models.Trip.departure_time <= end,
        )
    else:
        query = query.filter(models.Trip.departure_time >= datetime.utcnow())

    trips = query.order_by(models.Trip.departure_time.asc()).all()
    return [service.decorate_trip_row(db, trip) for trip in trips]


# ---------------------------------------------------------------------------
# Provider-only: create / delete trips
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.TripCreatedResponse, status_code=201)
def create_trip(
    payload: schemas.CreateTripRequest,
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """
    Provider-only. Creates a Route (reused if origin/destination already
    exists), a Bus with the validated 45- or 48-seat layout, the Trip itself,
    and all Seat rows — atomically.
    """
    trip = service.create_trip(
        db=db,
        origin=payload.origin,
        destination=payload.destination,
        total_seats=payload.total_seats,
        departure_time=payload.departure_time,
        price=payload.price,
        provider_id=provider.id,
    )
    return {
        "trip_id": trip.id,
        "origin": payload.origin,
        "destination": payload.destination,
        "departure_time": trip.departure_time,
        "total_seats": payload.total_seats,
        "price": trip.price,
        "message": f"Trip {trip.id} created with {payload.total_seats} seats.",
    }


@router.get("/mine", response_model=List[schemas.TripSearchResponse])
def list_my_trips(
    db: Session = Depends(get_db),
    provider=Depends(require_active_provider),
):
    """Provider's own trips only — enforces data isolation between providers."""
    trips = (
        db.query(models.Trip)
        .filter(models.Trip.provider_id == provider.id)
        .order_by(models.Trip.departure_time.asc())
        .all()
    )
    return [service.decorate_trip_row(db, trip) for trip in trips]


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
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    from fastapi import HTTPException
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.provider_id != provider.id:
        raise HTTPException(
            status_code=403,
            detail="You can only delete trips you own.",
        )
    service.delete_trip(db=db, trip_id=trip_id)
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
