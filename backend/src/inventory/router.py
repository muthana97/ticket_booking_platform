from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from ..database import get_db
from . import models, schemas

# 1. Define the router at the top
router = APIRouter(prefix="/trips", tags=["Inventory"])

# 2. Search endpoint (The code you shared)
@router.get("/search", response_model=List[schemas.TripSearchResponse])
def search_trips(
    origin: str, 
    destination: str, 
    travel_date: datetime, 
    db: Session = Depends(get_db)
):
    trips = db.query(models.Trip).join(models.Route).filter(
        models.Route.origin.ilike(f"%{origin}%"),
        models.Route.destination.ilike(f"%{destination}%"),
        models.Trip.departure_time >= travel_date.replace(hour=0, minute=0, second=0),
        models.Trip.departure_time <= travel_date.replace(hour=23, minute=59, second=59)
    ).all()

    results = []
    for trip in trips:
        available_count = db.query(models.Seat).filter(
            models.Seat.trip_id == trip.id,
            models.Seat.status == "available"
        ).count()

        results.append({
            "trip_id": trip.id,
            "provider_name": f"Provider {trip.provider_id}",
            "departure_time": trip.departure_time,
            "arrival_time": None,
            "price": trip.price,
            "available_seats_count": available_count
        })
    return results

# 3. Seat Map endpoint (Add this placeholder to satisfy SEAT-01)
@router.get("/{trip_id}/seats")
def get_trip_seat_map(trip_id: int, db: Session = Depends(get_db)):
    return {"message": "Seat map logic coming next"}
