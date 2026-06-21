from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, UniqueConstraint,
)
from ..database import Base


class CommissionRule(Base):
    __tablename__ = "commission_rules"
    __table_args__ = (
        UniqueConstraint(
            "scope", "provider_id", "route_id", "trip_id",
            name="uq_commission_rule_target",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String, nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True, index=True)
    rate_kind = Column(String, nullable=False)
    rate_value = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
