"""
Seed: builds two providers (for data-isolation testing), 4 trips, sample
bookings across statuses, and the admin / demo customer accounts.

Admin credentials are read from env (ADMIN_EMAIL / ADMIN_PASSWORD) so prod
can override the committed defaults without a code change. Demo customer +
provider accounts stay hardcoded — they're disposable demo data.

Run from the backend directory:
    ./venv/bin/python seed.py
"""

import os
from datetime import datetime, timedelta

from src.auth.models import User
from src.auth.utils import hash_password
from src.booking.models import Booking, Passenger
from src.database import SessionLocal
from src.inventory.models import Bus, Route, Seat, Trip
from src.inventory.service import build_layout_config, generate_seat_names


# ---------------------------------------------------------------------------
# Admin — overridable via env so prod can set its own credentials
# ---------------------------------------------------------------------------

ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL",    "admin@tazkirati.app")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "TazAdmin#MVP-2026")

# Demo accounts (customer + two providers) — hardcoded; rotate by editing
# this file. These exist purely to populate the stakeholder demo.
CUSTOMER_EMAIL    = "passenger@tazkirati.app"
CUSTOMER_PASSWORD = "Passenger#2026"
NILE_EMAIL        = "operator@tazkirati.app"
NILE_PASSWORD     = "NileOps#2026"
SUDAN_EMAIL       = "ops@sudanbus.app"
SUDAN_PASSWORD    = "SudanOps#2026"


def _build_seats(db, trip, total_seats):
    for name in generate_seat_names(total_seats):
        db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))
    # Flush so the seats are queryable by subsequent _seed_sample_bookings calls
    # (the session has autoflush=False so queries won't trigger this for us).
    db.flush()


def _seed_trip(db, *, route, provider_id, total_seats, days_offset, price):
    bus = Bus(
        provider_id=provider_id,
        name=f"Coach {total_seats}-Seater",
        total_seats=total_seats,
        seat_layout_config=build_layout_config(total_seats),
    )
    db.add(bus)
    db.flush()
    trip = Trip(
        provider_id=provider_id,
        route_id=route.id,
        bus_id=bus.id,
        departure_time=datetime.utcnow() + timedelta(days=days_offset),
        price=price,
    )
    db.add(trip)
    db.flush()
    _build_seats(db, trip, total_seats)
    return trip


def _seed_sample_bookings(db, *, customer, trip, seats, status, channel="consumer"):
    """Create a sample booking + flip the corresponding seats to the right state."""
    now = datetime.utcnow()
    seat_objs = (
        db.query(Seat)
        .filter(Seat.trip_id == trip.id, Seat.seat_number.in_(seats))
        .all()
    )

    if status == "pending":
        expires_at = now + timedelta(minutes=10)
        seat_state = "locked"
        billing_ref = None
        payment_status = "unpaid"
        payment_method = None
        bill_generated_at = None
    elif status == "committed_pending":
        expires_at = now + timedelta(minutes=30)
        seat_state = "locked"
        billing_ref = f"BOK-{trip.id:04d}-{len(seats):02d}"
        payment_status = "unpaid"
        payment_method = "billing_reference"
        bill_generated_at = now
    elif status == "confirmed":
        expires_at = now + timedelta(minutes=30)
        seat_state = "booked"
        billing_ref = f"BOK-{trip.id:04d}-{len(seats):02d}"
        payment_status = "paid"
        payment_method = "admin_confirmed"
        bill_generated_at = now
    else:
        raise ValueError(f"unknown sample status {status}")

    for s in seat_objs:
        s.status = seat_state

    b = Booking(
        customer_id=customer.id,
        trip_id=trip.id,
        status=status,
        channel=channel,
        total_price=trip.price * len(seats),
        payment_method=payment_method,
        payment_status=payment_status,
        billing_reference=billing_ref,
        bill_generated_at=bill_generated_at,
        created_at=now,
        expires_at=expires_at,
        seat_ids=[s.id for s in seat_objs],
    )
    db.add(b)
    db.flush()
    for s in seat_objs:
        db.add(Passenger(
            booking_id=b.id,
            full_name=customer.full_name or "Test Passenger",
            phone_number=customer.phone_number or "—",
            seat_number=s.seat_number,
        ))
    return b


def seed_data():
    db = SessionLocal()
    try:
        # ----- Users -----
        admin = User(
            email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD),
            full_name="System Administrator", role="admin", status="active",
            email_verified=True,
        )
        customer = User(
            email=CUSTOMER_EMAIL, password_hash=hash_password(CUSTOMER_PASSWORD),
            full_name="Amira Hassan", phone_number="249123456789",
            role="customer", status="active", email_verified=True,
        )
        nile = User(
            email=NILE_EMAIL, password_hash=hash_password(NILE_PASSWORD),
            full_name="Nile Coach Co.", phone_number="249900000001",
            role="provider", status="active", email_verified=True,
        )
        sudanbus = User(
            email=SUDAN_EMAIL, password_hash=hash_password(SUDAN_PASSWORD),
            full_name="SudanBus Express", phone_number="249900000002",
            role="provider", status="active", email_verified=True,
        )
        db.add_all([admin, customer, nile, sudanbus])
        db.flush()

        # ----- Routes -----
        krt_pzu = Route(origin="Khartoum", destination="Port Sudan", distance=800, duration="12h")
        krt_atb = Route(origin="Khartoum", destination="Atbara",     distance=310, duration="5h")
        krt_kss = Route(origin="Khartoum", destination="Kassala",    distance=560, duration="8h")
        db.add_all([krt_pzu, krt_atb, krt_kss])
        db.flush()

        # ----- Trips -----
        # Nile Coach Co. operates two trips
        t1 = _seed_trip(db, route=krt_pzu, provider_id=nile.id, total_seats=45, days_offset=1, price=15000.0)
        t2 = _seed_trip(db, route=krt_pzu, provider_id=nile.id, total_seats=48, days_offset=2, price=16000.0)
        # SudanBus Express operates two different routes
        t3 = _seed_trip(db, route=krt_atb, provider_id=sudanbus.id, total_seats=45, days_offset=1, price=11000.0)
        t4 = _seed_trip(db, route=krt_kss, provider_id=sudanbus.id, total_seats=48, days_offset=3, price=13500.0)

        # ----- Sample customer bookings -----
        # Awaiting payment (committed_pending)
        _seed_sample_bookings(db, customer=customer, trip=t1, seats=["5A", "5B"],
                              status="committed_pending")
        # Upcoming (confirmed, future departure — t2/t3/t4 all in future)
        _seed_sample_bookings(db, customer=customer, trip=t3, seats=["3A"],
                              status="confirmed")
        # A historical confirmed booking on a trip already departed (force past via overriding trip.departure_time)
        past_trip = Trip(
            provider_id=nile.id,
            route_id=krt_atb.id,
            bus_id=t1.bus_id,
            departure_time=datetime.utcnow() - timedelta(days=14),
            price=10000.0,
        )
        db.add(past_trip)
        db.flush()
        _build_seats(db, past_trip, 45)
        _seed_sample_bookings(db, customer=customer, trip=past_trip, seats=["7A", "7B"],
                              status="confirmed")

        db.commit()
        print(
            "✅ Seed complete.\n"
            "\nDemo credentials:\n"
            f"   ADMIN     {ADMIN_EMAIL:<32} pw: {ADMIN_PASSWORD}\n"
            f"   CUSTOMER  {CUSTOMER_EMAIL:<32} pw: {CUSTOMER_PASSWORD}\n"
            f"   NILE      {NILE_EMAIL:<32} pw: {NILE_PASSWORD}\n"
            f"   SUDANBUS  {SUDAN_EMAIL:<32} pw: {SUDAN_PASSWORD}\n"
            "\nSeeded fleet:\n"
            f"   Nile Coach Co.  → Trip {t1.id} (KRT→PZU 45-seat) + Trip {t2.id} (KRT→PZU 48-seat)\n"
            f"   SudanBus Exp.   → Trip {t3.id} (KRT→ATB 45-seat) + Trip {t4.id} (KRT→KSS 48-seat)\n"
            f"   + Trip {past_trip.id} (past-departure, used to populate 'My Tickets · Past')\n"
            "\nSeeded customer bookings:\n"
            "   • 1 committed_pending (Awaiting Payment)\n"
            "   • 1 confirmed (Upcoming)\n"
            "   • 1 confirmed (Past — departure was 2 weeks ago)\n"
        )
    except Exception as e:
        db.rollback()
        print(f"❌ Error during seeding: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
