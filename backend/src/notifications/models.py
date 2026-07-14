from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from ..database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Short kebab-case event key (e.g. "trip_time_changed",
    # "trip_edited_by_admin"). The frontend keys per-type rendering + click
    # routing off of this.
    type = Column(String, nullable=False)
    # Type-specific data. Kept as opaque JSON so we don't need a schema
    # migration for every new notification variety.
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    # NULL = unread. Set to the moment the user marks it read.
    read_at = Column(DateTime, nullable=True)
