from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from . import service, schemas
# from ..auth.dependencies import get_current_user # To be implemented next

router = APIRouter(prefix="/bookings", tags=["Bookings"])

@router.post("/lock")
def reserve_seats(
    payload: schemas.BookingLockRequest, 
    db: Session = Depends(get_db)
    # user = Depends(get_current_user) 
):
    """
    SEAT-04: Locks seats for 10-15 minutes.
    Requires atomic transaction to prevent double booking.
    """
    seats = service.lock_seats(db, payload.trip_id, payload.seat_numbers)
    return {"message": "Seats locked successfully", "expires_in": "15 minutes"}
