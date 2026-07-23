from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from ..database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=True)
    target_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=False)
    # Use JSONB on Postgres, JSON on SQLite. `metadata` is a reserved
    # SQLAlchemy attribute name (Declarative.metadata), so store under
    # metadata_ Python-side, exposed via .metadata_ everywhere.
    metadata_ = Column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_events_provider_created", "provider_id", "created_at"),
        Index(
            "ix_audit_events_provider_type_created",
            "provider_id",
            "event_type",
            "created_at",
        ),
    )
