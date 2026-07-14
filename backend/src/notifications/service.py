"""Notification service — thin helpers over the Notification model.

Every caller uses these helpers rather than instantiating Notification()
directly so the shape stays consistent (default payload={}, created_at
stamp, commit on write) and so the emit points across the codebase are
grep-able."""
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .models import Notification


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_notification(
    db: Session,
    *,
    user_id: int,
    type: str,
    payload: dict[str, Any] | None = None,
) -> Notification:
    n = Notification(user_id=user_id, type=type, payload=payload or {}, created_at=_now())
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def create_notifications_bulk(
    db: Session,
    *,
    user_ids: Iterable[int],
    type: str,
    payload: dict[str, Any] | None = None,
) -> int:
    """Fan out one notification per user_id in a single commit. Skips falsy
    ids (0 / None) so callers can pass raw booking.customer_id without
    guarding walk-ins where customer_id is the provider's own id and
    would produce a self-notify."""
    p = payload or {}
    now = _now()
    count = 0
    for uid in user_ids:
        if not uid:
            continue
        db.add(Notification(user_id=uid, type=type, payload=p, created_at=now))
        count += 1
    if count:
        db.commit()
    return count


def list_for_user(db: Session, *, user_id: int, limit: int = 50) -> tuple[int, list[Notification]]:
    """Return (unread_count, most_recent_items). Ordered newest-first."""
    items = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )
    return unread, items


def mark_read(db: Session, *, user_id: int, notification_id: int) -> Notification:
    from fastapi import HTTPException
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if n is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if n.read_at is None:
        n.read_at = _now()
        db.commit()
        db.refresh(n)
    return n


def mark_all_read(db: Session, *, user_id: int) -> int:
    n = _now()
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({"read_at": n}, synchronize_session=False)
    )
    db.commit()
    return updated
