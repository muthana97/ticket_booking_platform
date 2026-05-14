import random
import datetime
from sqlalchemy.orm import Session
from . import models

def generate_otp(db: Session, phone_number: str):
    # Generate a 6-digit code
    code = f"{random.randint(100000, 999999)}"
    expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    
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

def verify_otp(db: Session, phone_number: str, code: str):
    otp_record = db.query(models.OTPVerification).filter(
        models.OTPVerification.phone_number == phone_number,
        models.OTPVerification.otp_code == code,
        models.OTPVerification.is_verified == False,
        models.OTPVerification.expires_at > datetime.datetime.utcnow()
    ).first()

    if otp_record:
        otp_record.is_verified = True
        db.commit()
        return True
    return False
