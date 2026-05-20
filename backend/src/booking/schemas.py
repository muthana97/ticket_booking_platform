from pydantic import BaseModel
from typing import List
from datetime import datetime

# --- Original Phase 4 Lock Schemas ---

class BookingLockRequest(BaseModel):
    trip_id: int
    seat_numbers: List[str]
    total_price: float  # Feeds core Booking record generation

class BookingResponse(BaseModel):
    booking_id: int
    status: str
    payment_status: str
    total_price: float
    expires_at: datetime
    seats: List[str]
    message: str

    class Config:
        from_attributes = True  # Allows Pydantic to read SQLAlchemy ORM objects natively


# --- New Phase 5 Billing Intent Schemas ---

class BillingIntentRequest(BaseModel):
    booking_id: int

class BillingIntentResponse(BaseModel):
    booking_id: int
    status: str
    payment_method: str
    billing_reference: str
    expires_at: datetime
    message: str

    class Config:
        from_attributes = True
