from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class TripSearchResponse(BaseModel):
    trip_id: int
    provider_name: str
    departure_time: datetime
    arrival_time: Optional[datetime] = None
    price: float
    available_seats_count: int

    class Config:
        from_attributes = True

class BusLayoutResponse(BaseModel):
    trip_id: int
    bus_name: str
    layout_type: str
    total_rows: int
    # We can add a list of individual seat schemas here later
