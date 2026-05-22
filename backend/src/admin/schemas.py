from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------------------------
# Provider management
# ---------------------------------------------------------------------------

class ProviderSummary(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    phone_number: Optional[str] = None
    status: str
    email_verified: bool
    created_at: datetime
    trip_count: int

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Pending payment confirmation
# ---------------------------------------------------------------------------

class PendingPaymentItem(BaseModel):
    booking_id: int
    billing_reference: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    customer_name: Optional[str] = None
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    seats: List[str]
    total_price: float
    status: str          # 'pending' | 'committed_pending'
    expires_at: datetime
    created_at: datetime


class ConfirmPaymentResponse(BaseModel):
    booking_id: int
    status: str
    payment_status: str
    delivered_to: Optional[EmailStr] = None
    message: str


# ---------------------------------------------------------------------------
# All-bookings table (admin search/filter)
# ---------------------------------------------------------------------------

class AdminBookingItem(BaseModel):
    booking_id: int
    status: str
    payment_status: str
    channel: str
    billing_reference: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    customer_name: Optional[str] = None
    provider_id: int
    provider_name: Optional[str] = None
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    seats: List[str]
    passenger_names: List[str]
    total_price: float
    created_at: datetime
