from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Outbound — trip search & detail
# ---------------------------------------------------------------------------

class TripSearchResponse(BaseModel):
    trip_id: int
    provider_id: int
    provider_name: Optional[str] = None
    route_id: Optional[int] = None
    origin: str
    destination: str
    departure_time: datetime
    duration: Optional[str] = None
    price: float
    total_seats: int
    available_seats_count: int

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Inbound — provider trip creation
# ---------------------------------------------------------------------------

FleetSize = Literal[45, 48]
RepeatKind = Literal["once", "daily", "weekly", "custom"]


class RepeatPattern(BaseModel):
    """How to schedule recurring trips. `kind="once"` ignores everything else.

    For `daily`:  one trip per day from departure_time → end_date (inclusive).
    For `weekly`: same weekday as departure_time, week by week, until end_date.
    For `custom`: one trip on each `days_of_week` (0=Mon..6=Sun) from departure
                  date until end_date.
    """
    kind: RepeatKind = "once"
    end_date: Optional[datetime] = None   # last date trips may be created on
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun


class CreateTripRequest(BaseModel):
    origin: str = Field(..., min_length=2, max_length=80)
    destination: str = Field(..., min_length=2, max_length=80)
    total_seats: FleetSize
    departure_time: datetime
    price: float = Field(..., gt=0)
    repeat: RepeatPattern = Field(default_factory=RepeatPattern)


class TripCreatedResponse(BaseModel):
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    total_seats: int
    price: float
    message: str


class TripsCreatedResponse(BaseModel):
    """Returned when one CreateTripRequest produces N trips (recurring)."""
    count: int
    trips: List[TripCreatedResponse]
    message: str


class TripUpdateRequest(BaseModel):
    """Partial update of a trip's price and/or departure time. Any field left
    None on the request is untouched. Price bumps only affect *new* bookings;
    existing bookings keep the price they were locked at."""
    price: Optional[float] = Field(None, gt=0)
    departure_time: Optional[datetime] = None
