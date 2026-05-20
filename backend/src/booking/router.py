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
    total_price = getattr(payload, "total_price", 0.0)

    result = service.lock_seats(
        db=db,
        trip_id=payload.trip_id,
        seat_numbers=payload.seat_numbers,
        customer_id=current_user.id,
        total_price=total_price
    )
    
    return {
        "booking_id": result["booking"].id,
        "status": result["booking"].status,
        "payment_status": result["booking"].payment_status,
        "total_price": result["booking"].total_price,
        "expires_at": result["booking"].expires_at,
        "seats": [seat.seat_number for seat in result["seats"]],
        "message": f"Seats successfully locked under authorization token for {current_user.phone_number}."
    }


@router.post("/intent/billing", response_model=schemas.BillingIntentResponse)
def commit_billing_intent(
    payload: schemas.BillingIntentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    PAY-04 (Path B): Commit to paying via Billing Reference.
    Generates a billing confirmation number and extends checkout lifecycle constraints to 30 minutes.
    """
    booking = service.create_billing_intent(
        db=db,
        booking_id=payload.booking_id,
        customer_id=current_user.id
    )

    return {
        "booking_id": booking.id,
        "status": booking.status,
        "payment_method": booking.payment_method,
        "billing_reference": booking.billing_reference,
        "expires_at": booking.expires_at,
        "message": "Billing intent declared successfully. Please settle payment within 30 minutes."
    }
@router.get("/trips/{trip_id}/manifest", response_model=schemas.TripManifestResponse)
def get_trip_manifest(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    MAN-02: Generates the structured passenger manifest for a trip.
    Restricted to authenticated operators/admins.
    """
    # Note: In a subsequent phase, you can filter current_user roles here 
    # to restrict access specifically to admin/provider accounts.
    
    manifest_data = service.compile_trip_manifest(db=db, trip_id=trip_id)
    return manifest_data
