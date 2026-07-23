from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def record_event(
    db: Session,
    *,
    actor_user_id: int,
    provider_id: int,
    event_type: str,
    summary: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Emit an audit event inside the caller's transaction.

    Uses a SAVEPOINT (nested transaction) so a failed insert rolls back only
    the savepoint — the caller's outer transaction stays clean. Any exception
    is swallowed and logged; the audit layer must NEVER break a mutation.

    Does NOT commit the outer transaction — the caller's own commit (or
    rollback) determines whether the audit row lands.
    """
    try:
        with db.begin_nested():
            db.add(models.AuditEvent(
                actor_user_id=actor_user_id,
                provider_id=provider_id,
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                metadata_=metadata,
            ))
    except Exception as e:  # noqa: BLE001 — intentional broad catch
        print(f"[AUDIT] record_event failed silently: {e!r}")


def query_log(
    db: Session,
    *,
    provider_id: int,
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    limit: int = 100,
    before_id: Optional[int] = None,
) -> tuple[list[models.AuditEvent], Optional[int]]:
    """Return (items, next_before_id). next_before_id is None when done."""
    limit = min(max(1, int(limit)), 500)
    query = db.query(models.AuditEvent).filter(models.AuditEvent.provider_id == provider_id)
    if q:
        query = query.filter(models.AuditEvent.summary.ilike(f"%{q}%"))
    if event_type:
        query = query.filter(models.AuditEvent.event_type == event_type)
    if from_ts:
        query = query.filter(models.AuditEvent.created_at >= from_ts)
    if to_ts:
        query = query.filter(models.AuditEvent.created_at <= to_ts)
    if before_id is not None:
        query = query.filter(models.AuditEvent.id < before_id)

    rows = query.order_by(models.AuditEvent.id.desc()).limit(limit + 1).all()

    if len(rows) > limit:
        next_before = rows[limit - 1].id
        rows = rows[:limit]
    else:
        next_before = None
    return rows, next_before
