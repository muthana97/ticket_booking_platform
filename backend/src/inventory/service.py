"""Inventory service — fleet layout helper + trip create/delete."""

from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException

from . import models
from ..auth.models import User
from ..booking.models import Booking


def decorate_trip_row(db: Session, trip: models.Trip) -> dict:
    """
    Materialize a Trip into the shape `TripSearchResponse` expects, including
    a lookup of the provider's display name. Used by every trip-listing
    endpoint so customer / provider / admin views all carry provider_name.
    """
    available = (
        db.query(models.Seat)
        .filter(models.Seat.trip_id == trip.id, models.Seat.status == "available")
        .count()
    )
    total = db.query(models.Seat).filter(models.Seat.trip_id == trip.id).count()
    provider_name = None
    if trip.provider_id:
        provider = db.query(User).filter(User.id == trip.provider_id).first()
        if provider:
            provider_name = provider.full_name
    return {
        "trip_id": trip.id,
        "provider_id": trip.provider_id or 0,
        "provider_name": provider_name,
        "origin": trip.route.origin,
        "destination": trip.route.destination,
        "departure_time": trip.departure_time,
        "duration": trip.route.duration,
        "price": trip.price,
        "total_seats": total,
        "available_seats_count": available,
    }


REGULAR_ROW_COUNT = 10
REGULAR_ROW_LABELS = ("A", "B", "C", "D")
BACK_ROW_LABELS = ("A", "B", "C", "D", "E")
FRONT_EXTRA_LABELS = ("F1", "F2", "F3")

ALLOWED_LAYOUTS = {45, 48}


def generate_seat_names(total_seats: int) -> list[str]:
    """
    Yield seat names for the chosen fleet layout — only 45 and 48 are accepted
    per MVP fleet constraints.

      - 45-seat: 10 rows × 2x2 + 5-seat back row
      - 48-seat: same + 3 front jump seats (F1/F2/F3)
    """
    if total_seats not in ALLOWED_LAYOUTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fleet layout: {total_seats}. Only 45 and 48 are supported.",
        )

    seat_names: list[str] = []

    if total_seats == 48:
        seat_names.extend(FRONT_EXTRA_LABELS)

    for row in range(1, REGULAR_ROW_COUNT + 1):
        for label in REGULAR_ROW_LABELS:
            seat_names.append(f"{row}{label}")

    back_row_number = REGULAR_ROW_COUNT + 1
    for label in BACK_ROW_LABELS:
        seat_names.append(f"{back_row_number}{label}")

    return seat_names


def build_layout_config(total_seats: int) -> dict:
    return {
        "config": "2x2",
        "regular_rows": REGULAR_ROW_COUNT,
        "regular_row_seats": len(REGULAR_ROW_LABELS),
        "back_row_seats": len(BACK_ROW_LABELS),
        "front_extras": list(FRONT_EXTRA_LABELS) if total_seats == 48 else [],
        "total_seats": total_seats,
    }


# ---------------------------------------------------------------------------
# Trip create / delete (provider RBAC enforced at router layer)
# ---------------------------------------------------------------------------

def _get_or_create_route(db: Session, origin: str, destination: str) -> models.Route:
    """Reuse an existing Route by exact origin/destination match; else create."""
    route = (
        db.query(models.Route)
        .filter(models.Route.origin == origin, models.Route.destination == destination)
        .first()
    )
    if route is None:
        route = models.Route(origin=origin, destination=destination, duration="12h")
        db.add(route)
        db.flush()
    return route


def create_trip(
    db: Session,
    *,
    origin: str,
    destination: str,
    total_seats: int,
    departure_time: datetime,
    price: float,
    provider_id: int,
) -> models.Trip:
    """
    Create a Route (reused if it already exists), a Bus with the validated
    fleet layout, the Trip itself, and all Seat rows in one transaction.
    """
    if total_seats not in ALLOWED_LAYOUTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fleet layout: {total_seats}. Only 45 and 48 are supported.",
        )
    if not origin.strip() or not destination.strip():
        raise HTTPException(status_code=400, detail="Origin and destination are required")
    if origin.strip().lower() == destination.strip().lower():
        raise HTTPException(status_code=400, detail="Origin and destination must differ")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")

    route = _get_or_create_route(db, origin.strip(), destination.strip())

    bus = models.Bus(
        provider_id=provider_id,
        name=f"Coach {total_seats}-Seater",
        total_seats=total_seats,
        seat_layout_config=build_layout_config(total_seats),
    )
    db.add(bus)
    db.flush()

    trip = models.Trip(
        provider_id=provider_id,
        route_id=route.id,
        bus_id=bus.id,
        departure_time=departure_time,
        price=price,
    )
    db.add(trip)
    db.flush()

    for name in generate_seat_names(total_seats):
        db.add(models.Seat(trip_id=trip.id, seat_number=name, status="available"))

    db.commit()
    db.refresh(trip)
    return trip


def delete_trip(db: Session, *, trip_id: int) -> None:
    """
    Remove a trip. Refuses if any confirmed booking exists for the trip;
    pending / committed_pending holds are allowed (the Reaper would clear
    them on schedule anyway).
    """
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")

    confirmed_count = (
        db.query(Booking)
        .filter(Booking.trip_id == trip_id, Booking.status == "confirmed")
        .count()
    )
    if confirmed_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete: {confirmed_count} confirmed booking(s) on this trip",
        )

    held_bookings = (
        db.query(Booking)
        .filter(Booking.trip_id == trip_id)
        .all()
    )
    for b in held_bookings:
        db.delete(b)  # Passenger cascades via relationship

    db.query(models.Seat).filter(models.Seat.trip_id == trip_id).delete(synchronize_session=False)
    bus_id = trip.bus_id
    db.delete(trip)

    other_trips_on_bus = (
        db.query(models.Trip).filter(models.Trip.bus_id == bus_id).count()
    )
    if other_trips_on_bus == 0:
        bus = db.query(models.Bus).filter(models.Bus.id == bus_id).first()
        if bus is not None:
            db.delete(bus)

    db.commit()
