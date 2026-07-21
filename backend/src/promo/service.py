"""
Promo service helpers: CRUD, decoration, resolve-by-code, and the pure
discount math used at lock time. The apply hook itself lives in
booking.service.lock_seats so the promo columns get persisted alongside
the rest of the booking snapshot.
"""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..auth.models import User
from ..inventory.models import Trip
from . import models


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _decorate(db: Session, p: models.PromoCode) -> dict:
    provider_name = None
    if p.provider_id:
        u = db.query(User).filter(User.id == p.provider_id).first()
        provider_name = u.full_name if u else None
    trip_label = None
    if p.trip_id:
        t = db.query(Trip).filter(Trip.id == p.trip_id).first()
        if t and t.route:
            trip_label = f"Trip #{t.id} · {t.route.origin} → {t.route.destination}"
        elif t:
            trip_label = f"Trip #{t.id}"
    return {
        "id": p.id,
        "code": p.code,
        "discount_kind": p.discount_kind,
        "discount_value": p.discount_value,
        "max_redemptions": p.max_redemptions,
        "redemption_count": p.redemption_count,
        "provider_id": p.provider_id,
        "provider_name": provider_name,
        "trip_id": p.trip_id,
        "trip_label": trip_label,
        "active": p.active,
        "created_at": p.created_at,
    }


def list_promos(db: Session) -> list[dict]:
    rows = db.query(models.PromoCode).order_by(models.PromoCode.created_at.desc()).all()
    return [_decorate(db, p) for p in rows]


def create_promo(db: Session, **fields) -> dict:
    code = fields["code"]
    if db.query(models.PromoCode).filter(models.PromoCode.code == code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Promo code already exists.")
    p = models.PromoCode(**fields)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _decorate(db, p)


def update_promo(db: Session, *, promo_id: int, patch: dict) -> dict:
    p = db.query(models.PromoCode).filter(models.PromoCode.id == promo_id).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promo not found.")
    for k, v in patch.items():
        if v is None and k != "provider_id" and k != "trip_id":
            continue  # skip omitted fields (partial update)
        # 0 clears the redemption cap
        if k == "max_redemptions" and v == 0:
            v = None
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return _decorate(db, p)


def delete_promo(db: Session, *, promo_id: int) -> None:
    p = db.query(models.PromoCode).filter(models.PromoCode.id == promo_id).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promo not found.")
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------------------
# Apply at lock time
# ---------------------------------------------------------------------------

def resolve_and_price(
    db: Session,
    *,
    code: str,
    trip: Trip,
    total_before: float,
) -> tuple[models.PromoCode, float]:
    """
    Validate a promo against a trip. Returns (promo_row, discount_amount).
    Raises 400/404 with an explanatory detail on any failure so the frontend
    can surface it as a toast.

    Applied against the raw seat total, not per-seat. discount_kind:
      - 'percentage': min(pct * total, total)
      - 'flat'      : min(value, total)  ← never negative-total the booking
    """
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Promo code is empty.")
    code_norm = code.strip().upper()
    p = db.query(models.PromoCode).filter(models.PromoCode.code == code_norm).first()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promo code not found.")
    if not p.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This promo is no longer active.")
    if p.max_redemptions is not None and p.redemption_count >= p.max_redemptions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This promo has reached its redemption limit.")
    if p.provider_id is not None and trip.provider_id != p.provider_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This promo isn't valid on this operator's trips.")
    if p.trip_id is not None and trip.id != p.trip_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This promo isn't valid on this trip.")

    if p.discount_kind == "percentage":
        discount = total_before * (p.discount_value / 100.0)
    else:  # flat
        discount = p.discount_value
    # Clamp: a discount can zero the booking out but never negative it.
    discount = min(discount, total_before)
    discount = round(discount, 2)
    return p, discount


def bump_redemption(db: Session, *, promo_id: Optional[int]) -> None:
    """Increment the redemption counter on payment confirmation. No-ops when
    the booking wasn't locked with a promo, or when the promo has since been
    deleted (SET NULL FK)."""
    if not promo_id:
        return
    p = db.query(models.PromoCode).filter(models.PromoCode.id == promo_id).first()
    if not p:
        return
    p.redemption_count = (p.redemption_count or 0) + 1
    db.commit()
