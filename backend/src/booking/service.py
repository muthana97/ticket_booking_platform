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
