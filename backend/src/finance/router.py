from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from . import schemas, service

router = APIRouter(
    prefix="/admin/commissions",
    tags=["Admin · Commissions"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=schemas.CommissionsReadResponse)
def get_commissions(db: Session = Depends(get_db)):
    g = service.get_global(db)
    return {
        "global": (
            {
                "rate_kind": g.rate_kind,
                "rate_value": g.rate_value,
                "updated_at": g.updated_at,
            }
            if g else None
        ),
        "overrides": service.list_overrides(db),
    }


@router.put("/global", response_model=schemas.GlobalRuleOut)
def put_global(payload: schemas.GlobalUpsertIn, db: Session = Depends(get_db)):
    payload.validate_value()
    rule = service.upsert_global(
        db, rate_kind=payload.rate_kind, rate_value=payload.rate_value,
    )
    return {
        "rate_kind": rule.rate_kind,
        "rate_value": rule.rate_value,
        "updated_at": rule.updated_at,
    }


@router.post("/overrides", response_model=schemas.OverrideRuleOut, status_code=201)
def create_override(payload: schemas.OverrideCreateIn, db: Session = Depends(get_db)):
    payload.validate_shape()
    rule = service.create_override(
        db,
        scope=payload.scope,
        provider_id=payload.provider_id,
        route_id=payload.route_id,
        trip_id=payload.trip_id,
        rate_kind=payload.rate_kind,
        rate_value=payload.rate_value,
    )
    return service._decorate_override(db, rule)


@router.patch("/overrides/{override_id}", response_model=schemas.OverrideRuleOut)
def patch_override(
    override_id: int,
    payload: schemas.OverrideUpdateIn,
    db: Session = Depends(get_db),
):
    if payload.rate_kind == "percentage" and not (0 < payload.rate_value <= 100):
        raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
    if payload.rate_kind == "flat_per_seat" and payload.rate_value <= 0:
        raise HTTPException(400, "Flat rate must be > 0")
    rule = service.update_override(
        db,
        override_id=override_id,
        rate_kind=payload.rate_kind,
        rate_value=payload.rate_value,
    )
    return service._decorate_override(db, rule)


@router.delete("/overrides/{override_id}", status_code=204)
def remove_override(override_id: int, db: Session = Depends(get_db)):
    service.delete_override(db, override_id=override_id)
    return None
