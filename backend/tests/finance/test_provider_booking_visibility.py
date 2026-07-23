import datetime as _dt


def test_provider_bookings_expose_commission_and_net(client, db, provider_user):
    """A confirmed consumer booking with a 10% commission exposes
    commission_amount=200 and net_amount=1800 on a 2000-SDG booking."""
    from src.inventory.models import Trip, Route, Bus, Seat
    from src.booking.models import Booking
    from src.finance.models import CommissionRule
    from src.admin.service import confirm_payment

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
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=2000.0, channel="consumer", payment_status="unpaid",
        seat_ids=[s.id for s in seats],
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    confirm_payment(db, booking_id=b.id, actor_user_id=provider_user.id)

    r = client.post(
        "/auth/login",
        json={"email": provider_user.email, "password": "Test#2026"},
    )
    token = r.json()["access_token"]
    r2 = client.get(
        "/bookings/provider/mine",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200, r2.text
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["commission_amount"] == 200.0
    assert rows[0]["net_amount"] == 1800.0


def test_unconfirmed_booking_has_null_commission(client, db, provider_user):
    from src.inventory.models import Trip, Route, Bus
    from src.booking.models import Booking

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
    b = Booking(
        customer_id=1, trip_id=trip.id, status="pending",
        total_price=2000.0, channel="consumer", payment_status="unpaid",
        seat_ids=[],
    )
    db.add(b)
    db.commit()

    r = client.post(
        "/auth/login",
        json={"email": provider_user.email, "password": "Test#2026"},
    )
    token = r.json()["access_token"]
    r2 = client.get(
        "/bookings/provider/mine",
        headers={"Authorization": f"Bearer {token}"},
    )
    rows = r2.json()
    assert rows[0]["commission_amount"] is None
    assert rows[0]["net_amount"] is None
