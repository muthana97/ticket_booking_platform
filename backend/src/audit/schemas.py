from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditActor(BaseModel):
    id: int
    full_name: str
    role: str


class AuditEventItem(BaseModel):
    id: int
    event_type: str
    actor: AuditActor
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    summary: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditEventItem]
    next_before_id: Optional[int] = None
