from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from . import service, schemas, models, utils

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/request-otp")
def request_otp(payload: schemas.OTPRequest, db: Session = Depends(get_db)):
    """
    AUTH-01: Generate and 'send' an OTP to the user's phone.
    """
    service.generate_otp(db, payload.phone_number)
    # In a real app, you don't return the OTP in the API response! 
    # But for development, it helps you test without an SMS gateway.
    return {"message": "OTP sent successfully"}

@router.post("/verify-otp", response_model=schemas.TokenResponse)
def verify_otp(payload: schemas.OTPVerify, db: Session = Depends(get_db)):
    """
    AUTH-01: Verify the OTP and log the user in.
    """
    # Ensure your service returns the User object on success
    user = service.verify_otp(db, payload.phone_number, payload.otp_code)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP"
        )
    
    # This is where the error was happening
    access_token = utils.create_access_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
