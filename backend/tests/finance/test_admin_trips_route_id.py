"""The Add Override modal's Route picker derives the route list from
/admin/trips response rows — they must carry `route_id`."""
import datetime as _dt


def test_admin_trips_response_exposes_route_id(client, db, auth_header, provider_user):
    from src.inventory.models import Trip, Route, Bus, Seat
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
    db.add(Seat(trip_id=trip.id, seat_number="1A", status="available"))
    db.commit()

    r = client.get("/admin/trips?time=all", headers=auth_header)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["route_id"] == route.id
