"""Deleting a rule must not fail when a confirmed booking already references
it via the snapshot column. The FK uses ON DELETE SET NULL so the historic
rate_kind / rate_value / amount stay intact while the pointer is dropped."""
import datetime as _dt

from src.admin.service import confirm_payment
from src.booking.models import Booking
from src.finance.models import CommissionRule
from src.finance import service as fin
from src.inventory.models import Trip, Route, Bus, Seat


def test_delete_override_after_snapshot_keeps_amount_nulls_pointer(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(
        provider_id=provider_user.id, name="B",
        seat_layout_config={}, total_seats=45,
    )
    db.add_all([route, bus])
    db.flush()
    trip = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=_dt.datetime(2030, 1, 1),
        price=1000.0,
    )
    db.add(trip)
    db.flush()
    seats = [
        Seat(trip_id=trip.id, seat_number=f"{i}A", status="locked")
        for i in range(1, 3)
    ]
    db.add_all(seats)
    db.commit()

    rule = fin.create_override(
        db, scope="provider", provider_id=provider_user.id,
        route_id=None, trip_id=None,
        rate_kind="percentage", rate_value=10.0,
    )

    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=2000.0, channel="consumer", payment_status="unpaid",
        seat_ids=[s.id for s in seats],
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    confirm_payment(db, booking_id=b.id)
    db.refresh(b)
    assert b.commission_amount == 200.0
    assert b.commission_rule_id == rule.id

    # Deletion must succeed even though the booking points at this rule.
    fin.delete_override(db, override_id=rule.id)

    db.refresh(b)
    assert b.commission_rule_id is None      # pointer nulled
    assert b.commission_amount == 200.0      # historic amount intact
    assert b.commission_rate_kind == "percentage"
    assert b.commission_rate_value == 10.0
