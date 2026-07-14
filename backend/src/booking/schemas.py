from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime


# ---------------------------------------------------------------------------
# Inbound: Seat locking (consumer + walk-in share this shape)
# ---------------------------------------------------------------------------

class PassengerInput(BaseModel):
    full_name: str
    phone_number: Optional[str] = None  # optional — captured for provider records only
    national_id: Optional[str] = None   # optional — captured for provider records only
    seat_number: str                    # Must match one of seat_numbers below


class BookingLockRequest(BaseModel):
    trip_id: int
    seat_numbers: List[str]
    total_price: float
    passengers: List[PassengerInput] = Field(default_factory=list)


class WalkInBookingRequest(BookingLockRequest):
    """
    Provider walk-in booking. Routes through the SAME atomic `lock_seats`
    transaction as consumer checkout — only difference is the `channel` tag
    on the resulting Booking row and that no JWT customer is required.
    """
    pass


# ---------------------------------------------------------------------------
# Outbound: Lock response (lightweight confirmation)
# ---------------------------------------------------------------------------

class BookingResponse(BaseModel):
    booking_id: int
    status: str
    channel: str
    payment_status: str
    total_price: float
    expires_at: datetime
    seats: List[str]
    message: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Inbound: Billing intent (Path B — Path A deferred to V2)
# ---------------------------------------------------------------------------

class BillingIntentRequest(BaseModel):
    booking_id: int


# ---------------------------------------------------------------------------
# Outbound: The Stakeholder Ticket — rich, human-readable JSON
# ---------------------------------------------------------------------------

class TripSummary(BaseModel):
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    duration: Optional[str] = None
    price_per_seat: float
    provider_name: Optional[str] = None


class PassengerSummary(BaseModel):
    full_name: str
    seat_number: Optional[str] = None
    phone_number: Optional[str] = None


class MyBookingItem(BaseModel):
    """Slim row for the customer's 'My Tickets' view."""
    booking_id: int
    status: str
    payment_status: str
    channel: str
    billing_reference: Optional[str] = None
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    seats: List[str]
    total_price: float
    created_at: datetime
    expires_at: datetime
    is_past: bool

    class Config:
        from_attributes = True


class ProviderBookingItem(BaseModel):
    """Slim row for the provider's 'Bookings' view (own trips only)."""
    booking_id: int
    status: str
    payment_status: str
    channel: str
    billing_reference: Optional[str] = None
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    seats: List[str]
    passenger_count: int
    total_price: float
    created_at: datetime
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    commission_amount: Optional[float] = None
    net_amount: Optional[float] = None

    class Config:
        from_attributes = True


class TicketResponse(BaseModel):
    """
    The Billing Intent response — a stakeholder-presentable ticket.
    Everything needed to render a printable receipt without further round-trips.
    """
    booking_id: int
    booking_status: str
    payment_status: str
    payment_method: str
    billing_reference: str  # e.g., "BOK-8392-10"
    bill_generated_at: datetime
    expires_at: datetime
    trip: TripSummary
    passengers: List[PassengerSummary]
    seats: List[str]
    total_price: float
    delivered_to: Optional[str] = None  # simulated email delivery target
    qr_payload: str          # text content the frontend encodes into a QR image (TKT-04)
    message: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Outbound: Real-time seat state (layout matrix for the frontend)
# ---------------------------------------------------------------------------

SeatStatus = Literal["available", "locked", "booked"]


class SeatState(BaseModel):
    seat_number: str
    status: SeatStatus


class SeatStateSnapshot(BaseModel):
    trip_id: int
    version: int          # monotonic; clients pass this back as ?since=
    total_seats: int
    available: int
    locked: int
    booked: int
    seats: List[SeatState]
    fetched_at: datetime


# ---------------------------------------------------------------------------
# Outbound: Operational manifest (provider/admin)
# ---------------------------------------------------------------------------

class ManifestPassengerItem(BaseModel):
    passenger_id: int
    full_name: str
    phone_number: Optional[str] = None
    national_id: Optional[str] = None
    seat_number: Optional[str] = None
    booking_id: int


class TripManifestResponse(BaseModel):
    trip_id: int
    total_confirmed_passengers: int
    generated_at: datetime
    manifest: List[ManifestPassengerItem]

    class Config:
        from_attributes = True
