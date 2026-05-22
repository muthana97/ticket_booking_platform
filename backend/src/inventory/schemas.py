from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Outbound — trip search & detail
# ---------------------------------------------------------------------------

class TripSearchResponse(BaseModel):
    trip_id: int
    provider_id: int
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


class CreateTripRequest(BaseModel):
    origin: str = Field(..., min_length=2, max_length=80)
    destination: str = Field(..., min_length=2, max_length=80)
    total_seats: FleetSize
    departure_time: datetime
    price: float = Field(..., gt=0)


class TripCreatedResponse(BaseModel):
    trip_id: int
    origin: str
    destination: str
    departure_time: datetime
    total_seats: int
    price: float
    message: str
