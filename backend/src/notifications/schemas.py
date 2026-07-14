from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: int
    type: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationsListResponse(BaseModel):
    unread: int
    items: list[NotificationItem]


class MarkReadResponse(BaseModel):
    id: int
    read_at: datetime


class MarkAllReadResponse(BaseModel):
    marked: int
