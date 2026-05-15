import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from . import models

def generate_otp(db: Session, phone_number: str):
    # Generate a 6-digit code
    code = f"{random.randint(100000, 999999)}"
    expiry = datetime.utcnow() + timedelta(minutes=5)
    
    # Store in DB
    db_otp = models.OTPVerification(
        phone_number=phone_number,
        otp_code=code,
        expires_at=expiry
    )
    db.add(db_otp)
    db.commit()
    
    # In production, this is where you'd call an SMS Gateway (e.g., Twilio)
    print(f"DEBUG: OTP for {phone_number} is {code}") 
    return code

def verify_otp(db: Session, phone_number: str, otp_code: str):
    # 1. Find the OTP record
    otp_record = db.query(models.OTPVerification).filter(
        models.OTPVerification.phone_number == phone_number,
        models.OTPVerification.otp_code == otp_code
    ).first()

    # 2. Check if it exists and is not expired
    if not otp_record or otp_record.expires_at < datetime.utcnow():
        return None  # Return None instead of False

    # 3. Success! Find and return the actual User object
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    
    # Optional: Delete the OTP record so it can't be reused
    db.delete(otp_record)
    db.commit()

    return user # <--- THIS MUST BE THE USER OBJECT, NOT 'TRUE'
