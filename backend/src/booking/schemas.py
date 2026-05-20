from pydantic import BaseModel
from typing import List
from datetime import datetime

class BookingLockRequest(BaseModel):
    trip_id: int
    seat_numbers: List[str]
    total_price: float  # Added to feed the core Booking record generation

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
