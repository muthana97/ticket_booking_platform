from pydantic import BaseModel
from typing import List

class BookingLockRequest(BaseModel):
    trip_id: int
    seat_numbers: List[str]
