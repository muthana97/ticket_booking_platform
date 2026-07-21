"""
Admin promo CRUD (under /admin/promos) + a customer-facing pre-validate
endpoint (under /promos) so the booking UI can give honest feedback
BEFORE the user hits Lock.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user, require_admin
from ..database import get_db
from ..inventory.models import Trip
from . import schemas, service

router = APIRouter(
    prefix="/admin/promos",
    tags=["Promos"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=List[schemas.PromoOut])
def list_promos(db: Session = Depends(get_db)):
    return service.list_promos(db)


@router.post("", response_model=schemas.PromoOut, status_code=201)
def create_promo(payload: schemas.PromoCreate, db: Session = Depends(get_db)):
    return service.create_promo(db, **payload.model_dump())


@router.patch("/{promo_id}", response_model=schemas.PromoOut)
def update_promo(
    promo_id: int,
    payload: schemas.PromoUpdate,
    db: Session = Depends(get_db),
):
    return service.update_promo(
        db, promo_id=promo_id, patch=payload.model_dump(exclude_unset=True),
    )


@router.delete("/{promo_id}", status_code=204)
def delete_promo(promo_id: int, db: Session = Depends(get_db)):
    service.delete_promo(db, promo_id=promo_id)
    return None


# ---------------------------------------------------------------------------
# Pre-validate — used by the booking screen's Apply button so we don't tell
# customers "Promo applied" for garbage codes.
# ---------------------------------------------------------------------------

validate_router = APIRouter(prefix="/promos", tags=["Promos"])


@validate_router.get("/validate")
def validate_promo(
    code: str = Query(..., min_length=1, max_length=40),
    trip_id: int = Query(..., ge=1),
    total_price: float = Query(..., gt=0),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """
    Same rules as lock-time (existence, active, time window, provider /
    route / trip scope) but without touching redemption_count. Returns the
    computed discount so the UI can preview the new total.

    Per-customer and per-account caps aren't checked here (they only bite
    at lock, and previewing is cheap enough that a stale-cap race isn't
    worth the extra query).
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    promo, discount = service.resolve_and_price(
        db, code=code, trip=trip, total_before=total_price,
    )
    return {
        "code": promo.code,
        "discount_kind": promo.discount_kind,
        "discount_value": promo.discount_value,
        "discount_amount": discount,
        "total_after": round(total_price - discount, 2),
    }
