from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


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
    # ADMIN-2 capability toggles — default True for existing rows.
    can_add_trips: bool = True
    can_edit_trips: bool = True
    can_delete_trips: bool = True
    # Reports visibility deliberately defaults False — an admin must opt each
    # provider in explicitly for financial visibility.
    can_view_reports: bool = False

    class Config:
        from_attributes = True


class ProviderCapabilitiesUpdate(BaseModel):
    """Partial update — any omitted field is left as-is."""
    can_add_trips: Optional[bool] = None
    can_edit_trips: Optional[bool] = None
    can_delete_trips: Optional[bool] = None
    can_view_reports: Optional[bool] = None


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


# ---------------------------------------------------------------------------
# Reports (financial + operational, monthly by confirmation date)
# ---------------------------------------------------------------------------

class ReportPeriod(BaseModel):
    from_: str = Field(..., alias="from")
    to: str

    class Config:
        populate_by_name = True


class FinancialByMonthRow(BaseModel):
    month: str          # "YYYY-MM"
    commission: float
    bookings: int


class FinancialByProviderRow(BaseModel):
    provider_id: int
    provider_name: str
    commission: float
    bookings: int


class FinancialSection(BaseModel):
    total_commission: float
    by_month: List[FinancialByMonthRow]
    by_provider: List[FinancialByProviderRow]


class OperationalByMonthRow(BaseModel):
    month: str
    bookings: int
    passengers: int
    consumer: int
    walkin: int


class OperationalByProviderRow(BaseModel):
    provider_id: int
    provider_name: str
    bookings: int
    passengers: int
    consumer: int
    walkin: int


class OperationalSection(BaseModel):
    total_bookings: int
    total_passengers: int
    by_month: List[OperationalByMonthRow]
    by_provider: List[OperationalByProviderRow]


class ReportsResponse(BaseModel):
    period: ReportPeriod
    financial: FinancialSection
    operational: OperationalSection
