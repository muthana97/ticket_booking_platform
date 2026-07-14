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
    """Return (unread_count, most_recent_items). Ordered newest-first.
    Enriches payloads with human-readable actor names for historical
    notifications that were written before those fields existed."""
    items = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    _decorate_actor_names(db, items)
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .count()
    )
    return unread, items


def _decorate_actor_names(db: Session, items: list[Notification]) -> None:
    """Backfill actor display names on notification payloads for the response.
    Mutation is in-memory only (no commit) — SQLAlchemy autocommit is off so
    the row on disk stays unchanged; only the outbound serialization sees the
    enriched payload. Batched per actor type to avoid N+1."""
    from ..auth.models import User

    provider_ids_needing_name: set[int] = set()
    for n in items:
        if n.type == "trip_edited_by_provider":
            p = n.payload or {}
            if not p.get("provider_name") and p.get("provider_id"):
                provider_ids_needing_name.add(p["provider_id"])

    if not provider_ids_needing_name:
        return

    rows = (
        db.query(User.id, User.full_name)
        .filter(User.id.in_(provider_ids_needing_name))
        .all()
    )
    name_by_id = {row.id: row.full_name for row in rows}

    for n in items:
        if n.type == "trip_edited_by_provider":
            p = dict(n.payload or {})
            if not p.get("provider_name") and p.get("provider_id") in name_by_id:
                p["provider_name"] = name_by_id[p["provider_id"]]
                n.payload = p


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
