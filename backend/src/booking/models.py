from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..database import Base

class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    
    # Core Status: pending, committed_pending, confirmed, cancelled, expired
    status = Column(String, default="pending")
    total_price = Column(Float)
    
    # --- Phase 5: Payment Routing & Deferred Intent Fields ---
    payment_method = Column(String, nullable=True)     # "bok_direct", "billing_ref", "cash"
    payment_status = Column(String, default="unpaid")   # "unpaid", "paid", "failed"
    billing_reference = Column(String, nullable=True, index=True) # Path B Ref Number
    bill_generated_at = Column(DateTime, nullable=True)
    
    # --- CAN-03: Cancellation & Refund Audit Trail Compliance ---
    refund_amount = Column(Float, nullable=True)
    refund_status = Column(String, nullable=True)       # "pending", "processed", "void"
    refund_processed_at = Column(DateTime, nullable=True)
    
    # Dynamic Timing for seat locks (Initial checkout lock: 10 mins)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))
    
    # Relationships
    passengers = relationship("Passenger", back_populates="booking")
    seat_ids = Column(JSON) # Storing as JSON list of IDs for the booking session


class Passenger(Base):
    __tablename__ = "passengers"
    
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"))
    full_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    national_id = Column(String, nullable=True) # MAN-01 requirement
    
    booking = relationship("Booking", back_populates="passengers")
