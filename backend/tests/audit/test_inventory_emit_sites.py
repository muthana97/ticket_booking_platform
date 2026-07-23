from datetime import datetime, timedelta

from src.audit import models as audit_models
from src.auth import models as auth_models
from src.auth.utils import hash_password


def _login_as(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_provider(db, email="p1@x.com"):
    u = auth_models.User(
        email=email, password_hash=hash_password("pw"), full_name="Prov One",
        role="provider", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _seed_admin(db, email="admin1@x.com"):
    u = auth_models.User(
        email=email, password_hash=hash_password("pw"), full_name="Admin One",
        role="admin", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _create_trip_body():
    return {
        "origin": "Cairo",
        "destination": "Aswan",
        "total_seats": 45,
        "departure_time": (datetime.utcnow() + timedelta(days=2)).isoformat(),
        "price": 500.0,
    }


def test_provider_create_trip_emits_trip_created(client, db):
    prov = _seed_provider(db)
    h = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=h)
    assert r.status_code == 200 or r.status_code == 201, r.text

    rows = db.query(audit_models.AuditEvent).all()
    # Recurring `once` pattern default → 1 row expected. If the endpoint
    # returns multiple trips, assert one row per created trip.
    trip_created = [r for r in rows if r.event_type == "trip_created"]
    assert len(trip_created) >= 1
    e = trip_created[0]
    assert e.actor_user_id == prov.id
    assert e.provider_id == prov.id
    assert e.target_type == "trip"
    assert "Cairo" in e.summary and "Aswan" in e.summary


def test_provider_update_trip_emits_trip_edited_with_before_after(client, db):
    prov = _seed_provider(db)
    h = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=h)
    trip_id = r.json()["trips"][0]["trip_id"] if "trips" in r.json() else r.json()[0]["trip_id"]

    # Clear pre-existing audit rows from the create call
    db.query(audit_models.AuditEvent).delete(); db.commit()

    r2 = client.patch(f"/trips/{trip_id}", json={"price": 600.0}, headers=h)
    assert r2.status_code == 200, r2.text

    edits = db.query(audit_models.AuditEvent).filter_by(event_type="trip_edited").all()
    assert len(edits) == 1
    e = edits[0]
    assert e.actor_user_id == prov.id
    assert e.provider_id == prov.id
    assert e.target_type == "trip" and e.target_id == trip_id
    assert e.metadata_ and e.metadata_.get("before", {}).get("price") == 500.0
    assert e.metadata_.get("after", {}).get("price") == 600.0


def test_admin_update_trip_emits_trip_edited_with_admin_actor(client, db):
    prov = _seed_provider(db)
    admin = _seed_admin(db)

    ph = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=ph)
    trip_id = r.json()["trips"][0]["trip_id"] if "trips" in r.json() else r.json()[0]["trip_id"]
    db.query(audit_models.AuditEvent).delete(); db.commit()

    ah = _login_as(client, admin.email, "pw")
    r2 = client.patch(f"/admin/trips/{trip_id}", json={"price": 700.0}, headers=ah)
    assert r2.status_code == 200, r2.text

    edits = db.query(audit_models.AuditEvent).filter_by(event_type="trip_edited").all()
    assert len(edits) == 1
    e = edits[0]
    assert e.actor_user_id == admin.id
    assert e.provider_id == prov.id  # still the provider's log


def test_provider_delete_trip_emits_trip_deleted(client, db):
    prov = _seed_provider(db)
    h = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=h)
    trip_id = r.json()["trips"][0]["trip_id"] if "trips" in r.json() else r.json()[0]["trip_id"]
    db.query(audit_models.AuditEvent).delete(); db.commit()

    r2 = client.delete(f"/trips/{trip_id}", headers=h)
    assert r2.status_code in (200, 204), r2.text

    dels = db.query(audit_models.AuditEvent).filter_by(event_type="trip_deleted").all()
    assert len(dels) == 1
    e = dels[0]
    assert e.actor_user_id == prov.id
    assert e.target_id == trip_id


def test_admin_delete_trip_emits_trip_deleted_with_admin_actor(client, db):
    prov = _seed_provider(db)
    admin = _seed_admin(db)
    ph = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=ph)
    trip_id = r.json()["trips"][0]["trip_id"] if "trips" in r.json() else r.json()[0]["trip_id"]
    db.query(audit_models.AuditEvent).delete(); db.commit()

    ah = _login_as(client, admin.email, "pw")
    r2 = client.delete(f"/admin/trips/{trip_id}", headers=ah)
    assert r2.status_code in (200, 204), r2.text

    dels = db.query(audit_models.AuditEvent).filter_by(event_type="trip_deleted").all()
    assert len(dels) == 1
    e = dels[0]
    assert e.actor_user_id == admin.id
    assert e.provider_id == prov.id


def test_rolled_back_update_leaves_no_audit_row(client, db):
    """If the update raises (e.g. past-departure block), no audit row."""
    prov = _seed_provider(db)
    h = _login_as(client, prov.email, "pw")
    r = client.post("/trips", json=_create_trip_body(), headers=h)
    trip_id = r.json()["trips"][0]["trip_id"] if "trips" in r.json() else r.json()[0]["trip_id"]
    db.query(audit_models.AuditEvent).delete(); db.commit()

    # Try to move departure into the past → 400
    past = (datetime.utcnow() - timedelta(days=1)).isoformat()
    r2 = client.patch(f"/trips/{trip_id}", json={"departure_time": past}, headers=h)
    assert r2.status_code == 400

    assert db.query(audit_models.AuditEvent).filter_by(event_type="trip_edited").count() == 0
