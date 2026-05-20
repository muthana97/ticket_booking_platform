from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .models import Booking
from ..inventory.models import Seat

def lock_seats(db: Session, trip_id: int, seat_numbers: list[str], customer_id: int, total_price: float):
    """
    Implements SEAT-02: Prevent double booking using atomic transactions.
    Uses 'with_for_update' to lock the rows in Postgres until the transaction ends,
    and initializes a corresponding state-tracked Booking record (Phase 5).
    """
    # 1. Select seats with a Row-Level Lock
    query = db.query(Seat).filter(
        Seat.trip_id == trip_id,
        Seat.seat_number.in_(seat_numbers)
    ).with_for_update()

    seats = query.all()

    # 2. Verify all requested seats exist and are available
    if len(seats) != len(seat_numbers):
        raise HTTPException(status_code=404, detail="One or more seats not found")

    for seat in seats:
        if seat.status != "available":
            raise HTTPException(status_code=400, detail=f"Seat {seat.seat_number} is already taken")

    # 3. Mark seats as locked (pending payment)
    for seat in seats:
        seat.status = "locked"

    # 4. Phase 5 Addition: Instantiate the core Booking transaction record
    # Set immediate checkout expiration window to 10 minutes from right now
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expiration_window = now_utc + timedelta(minutes=10)

    # Collect internal primary IDs for JSON database tracking
    seat_ids_list = [seat.id for seat in seats]

    new_booking = Booking(
        customer_id=customer_id,
        trip_id=trip_id,
        status="pending",
        total_price=total_price,
        payment_status="unpaid",       # Tracks initial intent state
        created_at=now_utc,
        expires_at=expiration_window,
        seat_ids=seat_ids_list          # Track the literal IDs for the Reaper daemon
    )

    db.add(new_booking)
    
    # 5. Commit the entire atomic unit safely
    db.commit()
    db.refresh(new_booking)
    
    return {"booking": new_booking, "seats": seats}
def create_billing_intent(db: Session, booking_id: int, customer_id: int):
    """
    Implements PAY-04 (Path B): Transition booking to 'committed_pending',
    generate a mock verifiable reference number, and extend the lock window by 30 minutes.
    """
    # 1. Fetch the booking using row-level locking to safely change state safely
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.customer_id == customer_id
    ).with_for_update().first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking record not found or unauthorized")

    # 2. Check if the booking has already expired or changed out of 'pending'
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if booking.expires_at < now_utc:
        raise HTTPException(status_code=400, detail="Booking hold window has already expired")
        
    if booking.status != "pending":
        raise HTTPException(status_code=400, detail=f"Booking is in an invalid state for checkout: {booking.status}")

    # 3. Generate a deterministically structured mock verification reference code (e.g., BOK-8392-10)
    random_digits = "".join(random.choices(string.digits, k=4))
    random_suffix = "".join(random.choices(string.digits, k=2))
    mock_ref = f"BOK-{random_digits}-{random_suffix}"

    # 4. Advance states and stretch the expiration window out by 30 minutes
    booking.status = "committed_pending"
    booking.payment_method = "billing_reference"
    booking.billing_reference = mock_ref
    booking.bill_generated_at = now_utc
    booking.expires_at = now_utc + timedelta(minutes=30)
    def compile_trip_manifest(db: Session, trip_id: int):
    """
    Implements MAN-02: Compiles the passenger list (manifesto) for an operational trip.
    Collects records only from bookings in 'confirmed' status.
    """
    # 1. Fetch confirmed bookings for this specific trip
    confirmed_bookings = db.query(Booking).filter(
        Booking.trip_id == trip_id,
        Booking.status == "confirmed"
    ).all()

    manifest_list = []

    # 2. Extract passenger lists mapped to those confirmed bookings
    for booking in confirmed_bookings:
        for p in booking.passengers:
            manifest_list.append(
                {
                    "passenger_id": p.id,
                    "full_name": p.full_name,
                    "phone_number": p.phone_number,
                    "national_id": p.national_id,
                    "booking_id": booking.id
                }
            )

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    return {
        "trip_id": trip_id,
        "total_confirmed_passengers": len(manifest_list),
        "generated_at": now_utc,
        "manifest": manifest_list
    }

    db.commit()
    db.refresh(booking)

    return booking
