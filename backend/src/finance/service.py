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
