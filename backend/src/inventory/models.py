from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    distance = Column(Float)
    duration = Column(String) # e.g., "4h 30m"
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)

class Bus(Base):
    __tablename__ = "buses"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, index=True) # Will link to Provider model later
    name = Column(String) # e.g., "Express 01"
    # Flexible layout: e.g., {"rows": 10, "config": "2x2"}
    seat_layout_config = Column(JSON, nullable=False)
    total_seats = Column(Integer, nullable=False)

class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, index=True)
    bus_id = Column(Integer, ForeignKey("buses.id"))
    route_id = Column(Integer, ForeignKey("routes.id"))
    departure_time = Column(DateTime, nullable=False)
    price = Column(Float, nullable=False)
    
    # Relationships
    bus = relationship("Bus")
    route = relationship("Route")
    seats = relationship("Seat", back_populates="trip")

class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    seat_number = Column(String, nullable=False) # e.g., "14A"
    # status: available, locked, booked
    status = Column(String, default="available")
    
    trip = relationship("Trip", back_populates="seats")
