"""Commission rules — resolution + snapshot.

Spec: docs/superpowers/specs/2026-06-21-commissions-design.md
"""
from sqlalchemy.orm import Session

from .models import CommissionRule


def resolve_rule(db: Session, trip) -> CommissionRule | None:
    """Return the most specific rule that applies to this trip.

    Precedence (most specific first):
        trip > provider_route > provider > global

    Returns None if no rule at any tier (commission is then 0).
    """
    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "trip",
                    CommissionRule.trip_id == trip.id)
            .first())
    if r:
        return r

    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "provider_route",
                    CommissionRule.provider_id == trip.provider_id,
                    CommissionRule.route_id == trip.route_id)
            .first())
    if r:
        return r

    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "provider",
                    CommissionRule.provider_id == trip.provider_id)
            .first())
    if r:
        return r

    return (db.query(CommissionRule)
              .filter(CommissionRule.scope == "global")
              .first())


def snapshot_commission(db: Session, booking, trip) -> None:
    """Set commission_* columns on the booking. Called once, at the
    moment a booking transitions to `confirmed`. Immutable thereafter.

    Walk-in bookings short-circuit to 0 regardless of any matching rule:
    the provider sold at their own counter, the platform took no cut.
    """
    if booking.channel == "walkin":
        booking.commission_amount = 0.0
        return

    rule = resolve_rule(db, trip)
    if rule is None:
        booking.commission_amount = 0.0
        return

    if rule.rate_kind == "percentage":
        amount = round(booking.total_price * (rule.rate_value / 100.0), 2)
    else:  # flat_per_seat
        seat_count = len(booking.seat_ids or [])
        amount = round(rule.rate_value * seat_count, 2)

    booking.commission_amount = amount
    booking.commission_rate_kind = rule.rate_kind
    booking.commission_rate_value = rule.rate_value
    booking.commission_rule_id = rule.id


# ---------------------------------------------------------------------------
# Admin-facing helpers (called from finance/router.py)
# ---------------------------------------------------------------------------

def get_global(db: Session):
    return (db.query(CommissionRule)
              .filter(CommissionRule.scope == "global")
              .first())


def upsert_global(db: Session, *, rate_kind: str, rate_value: float):
    rule = get_global(db)
    if rule is None:
        rule = CommissionRule(
            scope="global", rate_kind=rate_kind, rate_value=rate_value,
        )
        db.add(rule)
    else:
        rule.rate_kind = rate_kind
        rule.rate_value = rate_value
    db.commit()
    db.refresh(rule)
    return rule


def create_override(
    db: Session, *, scope: str, provider_id: int,
    route_id: int | None, trip_id: int | None,
    rate_kind: str, rate_value: float,
):
    from fastapi import HTTPException

    if scope == "trip":
        from ..inventory.models import Trip as _Trip
        trip = db.query(_Trip).filter(_Trip.id == trip_id).first()
        if not trip:
            raise HTTPException(404, f"Trip {trip_id} not found")
        if trip.provider_id != provider_id:
            raise HTTPException(
                400,
                "Trip does not belong to the named provider — pick the trip's actual operator.",
            )

    existing = (db.query(CommissionRule)
                  .filter(CommissionRule.scope == scope,
                          CommissionRule.provider_id == provider_id,
                          CommissionRule.route_id == route_id,
                          CommissionRule.trip_id == trip_id)
                  .first())
    if existing:
        raise HTTPException(
            409, "Override already exists for this target — edit it instead.",
        )

    rule = CommissionRule(
        scope=scope, provider_id=provider_id,
        route_id=route_id, trip_id=trip_id,
        rate_kind=rate_kind, rate_value=rate_value,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_override(db: Session, *, override_id: int, rate_kind: str, rate_value: float):
    from fastapi import HTTPException
    rule = (db.query(CommissionRule)
              .filter(CommissionRule.id == override_id,
                      CommissionRule.scope != "global")
              .first())
    if not rule:
        raise HTTPException(404, "Override not found")
    rule.rate_kind = rate_kind
    rule.rate_value = rate_value
    db.commit()
    db.refresh(rule)
    return rule


def delete_override(db: Session, *, override_id: int) -> None:
    from fastapi import HTTPException
    rule = (db.query(CommissionRule)
              .filter(CommissionRule.id == override_id,
                      CommissionRule.scope != "global")
              .first())
    if not rule:
        raise HTTPException(404, "Override not found")
    db.delete(rule)
    db.commit()


def _decorate_override(db: Session, rule: CommissionRule) -> dict:
    """Hydrate human-readable labels the frontend renders."""
    from ..auth.models import User
    from ..inventory.models import Trip as _Trip, Route as _Route

    provider = db.query(User).filter(User.id == rule.provider_id).first()
    out = {
        "id": rule.id,
        "scope": rule.scope,
        "provider_id": rule.provider_id,
        "provider_name": provider.full_name if provider else "—",
        "route_id": rule.route_id,
        "route_label": None,
        "trip_id": rule.trip_id,
        "trip_label": None,
        "rate_kind": rule.rate_kind,
        "rate_value": rule.rate_value,
        "updated_at": rule.updated_at,
    }
    if rule.route_id:
        route = db.query(_Route).filter(_Route.id == rule.route_id).first()
        if route:
            out["route_label"] = f"{route.origin} → {route.destination}"
    if rule.trip_id:
        trip = db.query(_Trip).filter(_Trip.id == rule.trip_id).first()
        if trip:
            out["trip_label"] = (
                f"Trip #{trip.id} · {trip.departure_time.strftime('%Y-%m-%d %H:%M')}"
            )
    return out


_SCOPE_ORDER = {"trip": 0, "provider_route": 1, "provider": 2}


def list_overrides(db: Session) -> list[dict]:
    """All non-global rules, sorted by specificity descending (trip first)."""
    rules = (db.query(CommissionRule)
               .filter(CommissionRule.scope != "global")
               .all())
    decorated = [_decorate_override(db, r) for r in rules]
    decorated.sort(key=lambda r: (_SCOPE_ORDER.get(r["scope"], 9), r["updated_at"]))
    return decorated
