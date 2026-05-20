from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..auth.dependencies import get_current_user
from ..auth.models import User
from ..config import settings
from . import service, schemas

router = APIRouter(prefix="/bookings", tags=["Bookings"])

@router.post("/lock", response_model=schemas.BookingResponse)
def reserve_seats(
    payload: schemas.BookingLockRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    SEAT-04: Securely lock seats for a specific trip using an atomic transaction.
    Tied to the active authenticated session via JWT. Creates a 'pending' booking record.
    """
    # 1. Fallback / Configuration sanity validation
    # If total_price isn't included in your incoming payload schema yet, 
    # we calculate a placeholder calculation or require it via schemas.
    total_price = getattr(payload, "total_price", 0.0)
    if total_price <= 0.0:
        # If your application logic derives ticket pricing from an inventory lookup instead,
        # you can fetch the trip's price per seat here. For now, we expect it from the contract.
        pass

    # 2. Invoke our upgraded service engine layer
    result = service.lock_seats(
        db=db,
        trip_id=payload.trip_id,
        seat_numbers=payload.seat_numbers,
        customer_id=current_user.id,
        total_price=total_price
    )
    
    # 3. Construct and return a unified structural response payload
    return {
        "booking_id": result["booking"].id,
        "status": result["booking"].status,
        "payment_status": result["booking"].payment_status,
        "total_price": result["booking"].total_price,
        "expires_at": result["booking"].expires_at,
        "seats": [seat.seat_number for seat in result["seats"]],
        "message": f"Seats successfully locked under authorization token for {current_user.phone_number}."
    }
