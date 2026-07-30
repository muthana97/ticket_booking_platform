"""Care admin lifecycle router. Full-admin-only.

Provides create / list / block / unblock. No deletion by design (see
service module docstring for rationale).
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from . import care_admin_service, schemas


router = APIRouter(prefix="/admin/care-admins", tags=["Care Admins"])


@router.post("", response_model=schemas.CareAdminSummary, status_code=201)
def create_care_admin(
    payload: schemas.CareAdminCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.create_care_admin(
        db, payload=payload, actor_user_id=admin.id,
    )


@router.get("", response_model=List[schemas.CareAdminSummary])
def list_care_admins(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.list_care_admins(db)


@router.post("/{care_admin_id}/block", response_model=schemas.CareAdminSummary)
def block_care_admin(
    care_admin_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.set_care_admin_status(
        db, care_admin_id=care_admin_id, new_status="blocked", actor_user_id=admin.id,
    )


@router.post("/{care_admin_id}/unblock", response_model=schemas.CareAdminSummary)
def unblock_care_admin(
    care_admin_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.set_care_admin_status(
        db, care_admin_id=care_admin_id, new_status="active", actor_user_id=admin.id,
    )
