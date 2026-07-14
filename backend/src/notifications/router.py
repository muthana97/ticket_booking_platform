from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..auth.models import User
from ..database import get_db
from . import schemas, service


router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/me", response_model=schemas.NotificationsListResponse)
def list_mine(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Latest 50 notifications for the caller, newest first. Includes both
    read and unread. Also returns the current unread count so the bell badge
    can update on the same round-trip."""
    unread, items = service.list_for_user(db, user_id=user.id)
    return {"unread": unread, "items": items}


@router.post("/{notification_id}/read", response_model=schemas.MarkReadResponse)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    n = service.mark_read(db, user_id=user.id, notification_id=notification_id)
    return {"id": n.id, "read_at": n.read_at}


@router.post("/read-all", response_model=schemas.MarkAllReadResponse)
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    marked = service.mark_all_read(db, user_id=user.id)
    return {"marked": marked}
