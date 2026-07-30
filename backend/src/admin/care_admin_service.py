"""Care admin lifecycle service. Full-admin-only surface — endpoint-level
guards enforce that; this module trusts its callers on authorization.

Block is terminal (no delete): preserves audit_events.actor_user_id on
payment confirms recorded by the affected care admin.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..audit import service as audit_svc
from ..auth import models as auth_models
from ..auth.utils import hash_password
from . import schemas


def create_care_admin(
    db: Session, *, payload: schemas.CareAdminCreate, actor_user_id: int,
) -> auth_models.User:
    existing = db.query(auth_models.User).filter(
        auth_models.User.email == payload.email
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already in use")

    user = auth_models.User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="care_admin",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # record_event() uses a nested SAVEPOINT internally and swallows its own
    # exceptions (see audit/service.py) — a failed audit insert can never
    # break this mutation, no extra try/except needed here.
    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=user.id,
        event_type="care_admin_created",
        target_type="user",
        target_id=user.id,
        summary=f"Care admin created: {user.full_name} ({user.email})",
        metadata={"care_admin_id": user.id, "care_admin_email": user.email},
    )
    db.commit()

    return user


def list_care_admins(db: Session) -> list[auth_models.User]:
    return (
        db.query(auth_models.User)
        .filter(auth_models.User.role == "care_admin")
        .order_by(auth_models.User.created_at.desc())
        .all()
    )


def _load_care_admin(db: Session, care_admin_id: int) -> auth_models.User:
    user = (
        db.query(auth_models.User)
        .filter(
            auth_models.User.id == care_admin_id,
            auth_models.User.role == "care_admin",
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Care admin not found")
    return user


def set_care_admin_status(
    db: Session, *, care_admin_id: int, new_status: str, actor_user_id: int,
) -> auth_models.User:
    assert new_status in ("active", "blocked")
    user = _load_care_admin(db, care_admin_id)
    user.status = new_status
    db.commit()
    db.refresh(user)

    event_type = "care_admin_blocked" if new_status == "blocked" else "care_admin_unblocked"
    verb = "blocked" if new_status == "blocked" else "unblocked"
    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=user.id,
        event_type=event_type,
        target_type="user",
        target_id=user.id,
        summary=f"Care admin {verb}: {user.full_name} ({user.email})",
        metadata={"care_admin_id": user.id, "care_admin_email": user.email},
    )
    db.commit()

    return user
