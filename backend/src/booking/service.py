from sqlalchemy.orm import Session
from sqlalchemy import select
from .models import Booking
from ..inventory.models import Seat
from fastapi import HTTPException

def lock_seats(db: Session, trip_id: int, seat_numbers: list[str]):
    """
    Implements SEAT-02: Prevent double booking using atomic transactions.
    Uses 'with_for_update' to lock the rows in Postgres until the transaction ends.
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
    
    db.commit()
    return seats
