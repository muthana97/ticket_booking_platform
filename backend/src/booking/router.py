from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth.dependencies import get_current_user # <--- New Import
from ..auth.models import User # <--- For type hinting
from . import service, schemas

router = APIRouter(prefix="/bookings", tags=["Bookings"])

@router.post("/lock")
def reserve_seats(
    payload: schemas.BookingLockRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # <--- Security Gate
):
    """
    SEAT-04: Locks seats for 10-15 minutes.
    Now tied to a specific user via JWT.
    """
    # Note: We can now pass current_user.id to the service if needed 
    # for creating the booking record.
    seats = service.lock_seats(db, payload.trip_id, payload.seat_numbers)
    return {
        "message": f"Hello {current_user.phone_number}, seats locked successfully", 
        "expires_in": f"{settings.SEAT_LOCK_DURATION_MINUTES} minutes"
    }
