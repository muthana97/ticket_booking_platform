from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from ..database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))

    # Lifecycle: pending → committed_pending → confirmed | expired
    status = Column(String, default="pending")
    total_price = Column(Float)

    # Channel: "consumer" (JWT customer) or "walkin" (provider-created at counter)
    channel = Column(String, default="consumer")

    # Phase 5: Billing Intent (Path B only — Path A deferred to V2 per CLAUDE.md)
    payment_method = Column(String, nullable=True)        # "billing_reference" | "cash"
    payment_status = Column(String, default="unpaid")     # "unpaid" | "paid"
    billing_reference = Column(String, nullable=True, index=True)
    bill_generated_at = Column(DateTime, nullable=True)

    # Hold window — Reaper reads expires_at to release seats
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))

    seat_ids = Column(JSON)  # list[int] of Seat.id — used by Reaper to revert seats

    # Commission snapshot — populated by finance.service.snapshot_commission
    # at confirmation. NULL for unconfirmed bookings. Walk-ins keep only
    # commission_amount=0 with the other three columns NULL (no rule won).
    commission_amount = Column(Float, nullable=True)
    commission_rate_kind = Column(String, nullable=True)
    commission_rate_value = Column(Float, nullable=True)
    commission_rule_id = Column(
        Integer,
        ForeignKey("commission_rules.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Set by admin.service.confirm_payment at the moment status flips to
    # `confirmed`. Drives the monthly bucket on /admin/reports.
    confirmed_at = Column(DateTime, nullable=True, index=True)

    passengers = relationship("Passenger", back_populates="booking", cascade="all, delete-orphan")


class Passenger(Base):
    __tablename__ = "passengers"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"))
    full_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)  # optional per GEN-1 (2026-07-13)
    national_id = Column(String, nullable=True)
    seat_number = Column(String, nullable=True)  # The seat this passenger occupies

    booking = relationship("Booking", back_populates="passengers")
