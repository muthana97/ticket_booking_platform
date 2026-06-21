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
