from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..database import Base

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    
    # status: pending, confirmed, cancelled, expired
    status = Column(String, default="pending")
    total_price = Column(Float)
    
    # Timing for seat locks (NFR-12: 5-minute lock)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))
    
    # Relationships
    passengers = relationship("Passenger", back_populates="booking")
    # For many-to-many relationship with seats if needed, but usually linked via ID
    seat_ids = Column(JSON) # Storing as JSON list of IDs for the booking session

class Passenger(Base):
    __tablename__ = "passengers"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"))
    full_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    national_id = Column(String, nullable=True) # MAN-01 requirement

    booking = relationship("Booking", back_populates="passengers")
