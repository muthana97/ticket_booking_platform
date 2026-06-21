"""Inventory service — fleet layout helper + trip create/delete."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException

from . import models
from ..auth.models import User
from ..booking.models import Booking


# Recurring trip safety cap — refuse to create more than this many in one shot.
MAX_RECURRING_TRIPS = 60
MAX_RECURRING_DAYS_HORIZON = 90


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
        "route_id": trip.route_id,
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
    # Departures must be in the future. Compare naive UTC to match how the
    # rest of the codebase stores timestamps.
    now_utc_naive = datetime.utcnow()
    dep_naive = departure_time.replace(tzinfo=None) if departure_time.tzinfo else departure_time
    if dep_naive <= now_utc_naive:
        raise HTTPException(
            status_code=400,
            detail="Departure time must be in the future.",
        )

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


def expand_repeat_pattern(
    *,
    start: datetime,
    kind: str,
    end_date: datetime | None,
    days_of_week: list[int] | None,
) -> list[datetime]:
    """Return the full list of departure datetimes implied by a repeat pattern.
    Includes `start` itself. Returns [start] for kind='once'.
    """
    if kind == "once":
        return [start]

    if end_date is None:
        raise HTTPException(
            status_code=400,
            detail="end_date is required when repeat is daily / weekly / custom.",
        )
    start_naive = start.replace(tzinfo=None) if start.tzinfo else start
    end_naive = end_date.replace(tzinfo=None) if end_date.tzinfo else end_date
    if end_naive <= start_naive:
        raise HTTPException(status_code=400, detail="end_date must be after departure.")
    horizon = start_naive + timedelta(days=MAX_RECURRING_DAYS_HORIZON)
    if end_naive > horizon:
        raise HTTPException(
            status_code=400,
            detail=f"end_date must be within {MAX_RECURRING_DAYS_HORIZON} days of departure.",
        )

    departures: list[datetime] = [start_naive]
    cursor = start_naive

    if kind == "daily":
        while True:
            cursor = cursor + timedelta(days=1)
            if cursor > end_naive:
                break
            departures.append(cursor)
    elif kind == "weekly":
        while True:
            cursor = cursor + timedelta(days=7)
            if cursor > end_naive:
                break
            departures.append(cursor)
    elif kind == "custom":
        if not days_of_week:
            raise HTTPException(
                status_code=400,
                detail="custom repeat requires days_of_week (0=Mon..6=Sun).",
            )
        wanted = {d for d in days_of_week if 0 <= d <= 6}
        cursor = start_naive
        # Walk one day at a time so we hit each requested weekday between
        # start (exclusive — already added) and end_date (inclusive).
        while cursor < end_naive:
            cursor = cursor + timedelta(days=1)
            if cursor.weekday() in wanted and cursor <= end_naive:
                departures.append(cursor)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown repeat kind: {kind}")

    if len(departures) > MAX_RECURRING_TRIPS:
        raise HTTPException(
            status_code=400,
            detail=f"Refusing to create {len(departures)} trips in one shot "
                   f"(cap is {MAX_RECURRING_TRIPS}).",
        )
    return departures


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
