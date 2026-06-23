"""Report aggregations for /admin/reports.

Pure functions over a database session — no router concerns. Bucketing is
by confirmation date (Booking.confirmed_at). Spec:
docs/superpowers/specs/2026-06-23-reports-design.md
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session


def period_months(from_str: str, to_str: str) -> list[str]:
    """Inclusive list of YYYY-MM strings from `from_str` to `to_str`."""
    from_y, from_m = map(int, from_str.split("-"))
    to_y, to_m = map(int, to_str.split("-"))
    out = []
    y, m = from_y, from_m
    while (y, m) <= (to_y, to_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _period_bounds(period: list[str]) -> tuple[datetime, datetime]:
    """Inclusive UTC datetime range for a list of YYYY-MM strings."""
    first_y, first_m = map(int, period[0].split("-"))
    last_y, last_m = map(int, period[-1].split("-"))
    start = datetime(first_y, first_m, 1)
    if last_m == 12:
        end_y, end_m = last_y + 1, 1
    else:
        end_y, end_m = last_y, last_m + 1
    end = datetime(end_y, end_m, 1)  # exclusive upper bound
    return start, end


def financial_by_month(
    db: Session, *, period: list[str], provider_id: Optional[int],
) -> list[dict]:
    """One row per month in `period`. Sums commission_amount where not NULL,
    counts bookings (confirmed only). Empty months appear with zeros."""
    from ..booking.models import Booking
    from ..inventory.models import Trip

    start, end = _period_bounds(period)

    q = (
        db.query(Booking, Trip)
        .join(Trip, Trip.id == Booking.trip_id)
        .filter(
            Booking.status == "confirmed",
            Booking.confirmed_at.isnot(None),
            Booking.confirmed_at >= start,
            Booking.confirmed_at < end,
        )
    )
    if provider_id is not None:
        q = q.filter(Trip.provider_id == provider_id)

    buckets: dict[str, dict] = {m: {"commission": 0.0, "bookings": 0} for m in period}
    for b, _t in q.all():
        # Spec §5: rows with commission_amount IS NULL are excluded entirely
        # from the financial side. Walk-ins keep amount=0.0 (not NULL) so they
        # still count here.
        if b.commission_amount is None:
            continue
        key = b.confirmed_at.strftime("%Y-%m")
        if key not in buckets:
            continue
        buckets[key]["bookings"] += 1
        buckets[key]["commission"] += b.commission_amount

    return [
        {"month": m, "commission": round(v["commission"], 2), "bookings": v["bookings"]}
        for m, v in buckets.items()
    ]


def financial_by_provider(
    db: Session, *, period: list[str], provider_id: Optional[int],
) -> list[dict]:
    """One row per provider with confirmed bookings + non-NULL commission in
    the period. Providers with zero qualifying activity are omitted."""
    from ..auth.models import User
    from ..booking.models import Booking
    from ..inventory.models import Trip

    start, end = _period_bounds(period)

    q = (
        db.query(Booking, Trip)
        .join(Trip, Trip.id == Booking.trip_id)
        .filter(
            Booking.status == "confirmed",
            Booking.confirmed_at.isnot(None),
            Booking.confirmed_at >= start,
            Booking.confirmed_at < end,
        )
    )
    if provider_id is not None:
        q = q.filter(Trip.provider_id == provider_id)

    buckets: dict[int, dict] = {}
    for b, t in q.all():
        # Same NULL exclusion as financial_by_month — financial-side only.
        if b.commission_amount is None:
            continue
        pid = t.provider_id
        if pid not in buckets:
            buckets[pid] = {"commission": 0.0, "bookings": 0}
        buckets[pid]["bookings"] += 1
        buckets[pid]["commission"] += b.commission_amount

    pids = list(buckets.keys())
    if not pids:
        return []
    name_by_id = {
        u.id: u.full_name
        for u in db.query(User).filter(User.id.in_(pids)).all()
    }

    return [
        {
            "provider_id": pid,
            "provider_name": name_by_id.get(pid, "—"),
            "commission": round(v["commission"], 2),
            "bookings": v["bookings"],
        }
        for pid, v in buckets.items()
    ]


def operational_by_month(
    db: Session, *, period: list[str], provider_id: Optional[int],
) -> list[dict]:
    """One row per month with booking + passenger + channel-split counts.
    Includes confirmed bookings regardless of commission state."""
    from sqlalchemy import func
    from ..booking.models import Booking, Passenger
    from ..inventory.models import Trip

    start, end = _period_bounds(period)

    bookings_q = (
        db.query(Booking, Trip)
        .join(Trip, Trip.id == Booking.trip_id)
        .filter(
            Booking.status == "confirmed",
            Booking.confirmed_at.isnot(None),
            Booking.confirmed_at >= start,
            Booking.confirmed_at < end,
        )
    )
    if provider_id is not None:
        bookings_q = bookings_q.filter(Trip.provider_id == provider_id)

    book_rows = bookings_q.all()
    booking_ids = [b.id for b, _ in book_rows]

    pax_count_by_booking: dict[int, int] = {}
    if booking_ids:
        for bid, n in (
            db.query(Passenger.booking_id, func.count(Passenger.id))
            .filter(Passenger.booking_id.in_(booking_ids))
            .group_by(Passenger.booking_id)
            .all()
        ):
            pax_count_by_booking[bid] = n

    buckets: dict[str, dict] = {
        m: {"bookings": 0, "passengers": 0, "consumer": 0, "walkin": 0}
        for m in period
    }
    for b, _t in book_rows:
        key = b.confirmed_at.strftime("%Y-%m")
        if key not in buckets:
            continue
        buckets[key]["bookings"] += 1
        buckets[key]["passengers"] += pax_count_by_booking.get(b.id, 0)
        if b.channel == "walkin":
            buckets[key]["walkin"] += 1
        else:
            buckets[key]["consumer"] += 1

    return [{"month": m, **v} for m, v in buckets.items()]


def operational_by_provider(
    db: Session, *, period: list[str], provider_id: Optional[int],
) -> list[dict]:
    """One row per provider with confirmed activity in the period.
    Counts include all confirmed rows regardless of commission state."""
    from sqlalchemy import func
    from ..auth.models import User
    from ..booking.models import Booking, Passenger
    from ..inventory.models import Trip

    start, end = _period_bounds(period)

    bookings_q = (
        db.query(Booking, Trip)
        .join(Trip, Trip.id == Booking.trip_id)
        .filter(
            Booking.status == "confirmed",
            Booking.confirmed_at.isnot(None),
            Booking.confirmed_at >= start,
            Booking.confirmed_at < end,
        )
    )
    if provider_id is not None:
        bookings_q = bookings_q.filter(Trip.provider_id == provider_id)

    book_rows = bookings_q.all()
    booking_ids = [b.id for b, _ in book_rows]

    pax_count_by_booking: dict[int, int] = {}
    if booking_ids:
        for bid, n in (
            db.query(Passenger.booking_id, func.count(Passenger.id))
            .filter(Passenger.booking_id.in_(booking_ids))
            .group_by(Passenger.booking_id)
            .all()
        ):
            pax_count_by_booking[bid] = n

    buckets: dict[int, dict] = {}
    for b, t in book_rows:
        pid = t.provider_id
        if pid not in buckets:
            buckets[pid] = {"bookings": 0, "passengers": 0,
                            "consumer": 0, "walkin": 0}
        buckets[pid]["bookings"] += 1
        buckets[pid]["passengers"] += pax_count_by_booking.get(b.id, 0)
        if b.channel == "walkin":
            buckets[pid]["walkin"] += 1
        else:
            buckets[pid]["consumer"] += 1

    pids = list(buckets.keys())
    if not pids:
        return []
    name_by_id = {
        u.id: u.full_name
        for u in db.query(User).filter(User.id.in_(pids)).all()
    }

    return [
        {"provider_id": pid, "provider_name": name_by_id.get(pid, "—"), **v}
        for pid, v in buckets.items()
    ]
