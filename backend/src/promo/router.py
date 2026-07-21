"""
Admin-only promo CRUD. Mounted under /admin/promos so it lives next to
the commissions routes structurally, but the router is defined here so
the promo package stays self-contained.
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
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
