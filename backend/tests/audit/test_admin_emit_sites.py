import datetime as _dt

from src.audit import models as audit_models
from src.auth import models as auth_models
from src.auth.utils import hash_password


def _login_as(client, email, password="pw"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db, role, status, email):
    u = auth_models.User(
        email=email, password_hash=hash_password("pw"), full_name=f"{role.title()} {email}",
        role=role, status=status, email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def test_approve_provider_emits_provider_approved(client, db):
    admin = _seed(db, "admin", "active", "a@x.com")
    prov = _seed(db, "provider", "pending", "p@x.com")
    h = _login_as(client, admin.email)
    r = client.post(f"/admin/providers/{prov.id}/approve", headers=h)
    assert r.status_code == 200, r.text

    row = db.query(audit_models.AuditEvent).filter_by(event_type="provider_approved").one()
    assert row.actor_user_id == admin.id
    assert row.provider_id == prov.id


def test_block_provider_emits_provider_blocked(client, db):
    admin = _seed(db, "admin", "active", "a@x.com")
    prov = _seed(db, "provider", "active", "p@x.com")
    h = _login_as(client, admin.email)
    r = client.post(f"/admin/providers/{prov.id}/block", headers=h)
    assert r.status_code == 200, r.text

    row = db.query(audit_models.AuditEvent).filter_by(event_type="provider_blocked").one()
    assert row.actor_user_id == admin.id
    assert row.provider_id == prov.id


def test_unblock_provider_emits_provider_unblocked(client, db):
    """Approving a blocked provider transitions blocked → active. Emit as
    provider_unblocked (not provider_approved) so UI icon distinguishes.

    Implementation note: set_provider_status maps new_status back to an event
    type. Approving a *pending* → provider_approved. Approving a *blocked*
    (i.e. blocked → active) → provider_unblocked."""
    admin = _seed(db, "admin", "active", "a@x.com")
    prov = _seed(db, "provider", "blocked", "p@x.com")
    h = _login_as(client, admin.email)
    r = client.post(f"/admin/providers/{prov.id}/approve", headers=h)
    assert r.status_code == 200, r.text

    row = db.query(audit_models.AuditEvent).filter_by(event_type="provider_unblocked").one()
    assert row.actor_user_id == admin.id
    assert row.provider_id == prov.id


def test_capability_toggle_emits_capability_changed(client, db):
    admin = _seed(db, "admin", "active", "a@x.com")
    prov = _seed(db, "provider", "active", "p@x.com")
    h = _login_as(client, admin.email)
    r = client.patch(
        f"/admin/providers/{prov.id}/capabilities",
        json={"can_add_trips": False},
        headers=h,
    )
    assert r.status_code == 200, r.text

    rows = db.query(audit_models.AuditEvent).filter_by(event_type="capability_changed").all()
    assert len(rows) == 1
    e = rows[0]
    assert e.actor_user_id == admin.id
    assert e.provider_id == prov.id
    assert e.metadata_ and e.metadata_.get("capability") == "can_add_trips"
    assert e.metadata_.get("to") is False
    assert "can_add_trips" in e.summary


def test_payment_confirm_emits_payment_confirmed(client, db):
    """Requires an existing committed_pending booking to confirm. Setup
    mirrors backend/tests/booking/test_confirm_path_snapshots_commission.py's
    `trip_with_seats` fixture + `_committed_booking` helper (inlined here
    since that file's fixture is function-scoped to its own module)."""
    from src.booking.models import Booking
    from src.inventory.models import Bus, Route, Seat, Trip

    admin = _seed(db, "admin", "active", "a@x.com")
    prov = _seed(db, "provider", "active", "p@x.com")

    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(
        provider_id=prov.id, name="B",
        seat_layout_config={}, total_seats=45,
    )
    db.add_all([route, bus])
    db.flush()
    trip = Trip(
        provider_id=prov.id, bus_id=bus.id, route_id=route.id,
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

    booking = Booking(
        customer_id=admin.id, trip_id=trip.id, status="committed_pending",
        total_price=2000.0, channel="consumer", payment_status="unpaid",
        seat_ids=[s.id for s in seats],
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    h = _login_as(client, admin.email)
    r = client.post(f"/admin/payments/{booking.id}/confirm", headers=h)
    assert r.status_code == 200, r.text

    row = db.query(audit_models.AuditEvent).filter_by(event_type="payment_confirmed").one()
    assert row.actor_user_id == admin.id
    assert row.provider_id == trip.provider_id
