"""Tests for GET /admin/providers/{provider_id}/log endpoint."""
from datetime import datetime, timedelta

from src.auth.models import User
from src.auth.utils import hash_password
from src.audit import models as audit_models


def test_provider_log_happy_path(client, auth_header, db, provider_user):
    """Happy path: returns items newest-first."""
    # Create a few audit events for this provider
    e1 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Trip #1 created: Cairo → Giza",
        target_type="trip",
        target_id=1,
        created_at=datetime.utcnow() - timedelta(hours=2),
    )
    e2 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_edited",
        summary="Trip #1 edited: price 500→600",
        target_type="trip",
        target_id=1,
        created_at=datetime.utcnow() - timedelta(hours=1),
    )
    e3 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_deleted",
        summary="Trip #1 deleted",
        target_type="trip",
        target_id=1,
        created_at=datetime.utcnow(),
    )
    db.add_all([e1, e2, e3])
    db.commit()

    r = client.get(f"/admin/providers/{provider_user.id}/log", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    # Newest first (id desc)
    assert body["items"][0]["event_type"] == "trip_deleted"
    assert body["items"][1]["event_type"] == "trip_edited"
    assert body["items"][2]["event_type"] == "trip_created"
    assert body["next_before_id"] is None


def test_provider_log_keyword_filter(client, auth_header, db, provider_user):
    """Keyword filter (q=Cairo) narrows to matching summaries."""
    e1 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Trip #1 created: Cairo → Giza",
        target_type="trip",
        target_id=1,
    )
    e2 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Trip #2 created: Khartoum → Port Sudan",
        target_type="trip",
        target_id=2,
    )
    db.add_all([e1, e2])
    db.commit()

    r = client.get(
        f"/admin/providers/{provider_user.id}/log?q=Cairo",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["summary"] == "Trip #1 created: Cairo → Giza"


def test_provider_log_event_type_filter(client, auth_header, db, provider_user):
    """event_type=trip_edited filter."""
    e1 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Trip #1 created",
        target_type="trip",
        target_id=1,
    )
    e2 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_edited",
        summary="Trip #1 edited",
        target_type="trip",
        target_id=1,
    )
    e3 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_edited",
        summary="Trip #2 edited",
        target_type="trip",
        target_id=2,
    )
    db.add_all([e1, e2, e3])
    db.commit()

    r = client.get(
        f"/admin/providers/{provider_user.id}/log?event_type=trip_edited",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert all(item["event_type"] == "trip_edited" for item in body["items"])


def test_provider_log_date_range_filter(client, auth_header, db, provider_user):
    """Date range from/to filter."""
    now = datetime.utcnow()
    e1 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Old trip",
        created_at=now - timedelta(days=10),
    )
    e2 = audit_models.AuditEvent(
        actor_user_id=1,
        provider_id=provider_user.id,
        event_type="trip_created",
        summary="Recent trip",
        created_at=now - timedelta(days=1),
    )
    db.add_all([e1, e2])
    db.commit()

    # Query only the last 5 days
    from_dt = now - timedelta(days=5)
    to_dt = now

    r = client.get(
        f"/admin/providers/{provider_user.id}/log?from={from_dt.isoformat()}&to={to_dt.isoformat()}",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["summary"] == "Recent trip"


def test_provider_log_cursor_pagination(client, auth_header, db, provider_user):
    """Cursor pagination: request limit=2 twice, get consecutive pages,
    next_before_id reaches null."""
    # Create 5 events
    for i in range(5):
        e = audit_models.AuditEvent(
            actor_user_id=1,
            provider_id=provider_user.id,
            event_type="trip_created",
            summary=f"Trip #{i+1}",
            created_at=datetime.utcnow() - timedelta(hours=4-i),
        )
        db.add(e)
    db.commit()

    # First page: limit=2
    r1 = client.get(
        f"/admin/providers/{provider_user.id}/log?limit=2",
        headers=auth_header,
    )
    assert r1.status_code == 200
    page1 = r1.json()
    assert len(page1["items"]) == 2
    assert page1["next_before_id"] is not None
    first_page_ids = [item["id"] for item in page1["items"]]

    # Second page: use the cursor
    r2 = client.get(
        f"/admin/providers/{provider_user.id}/log?limit=2&before_id={page1['next_before_id']}",
        headers=auth_header,
    )
    assert r2.status_code == 200
    page2 = r2.json()
    assert len(page2["items"]) == 2
    assert page2["next_before_id"] is not None
    second_page_ids = [item["id"] for item in page2["items"]]

    # Third page: use the cursor (should get the last 1 item)
    r3 = client.get(
        f"/admin/providers/{provider_user.id}/log?limit=2&before_id={page2['next_before_id']}",
        headers=auth_header,
    )
    assert r3.status_code == 200
    page3 = r3.json()
    assert len(page3["items"]) == 1
    assert page3["next_before_id"] is None
    third_page_ids = [item["id"] for item in page3["items"]]

    # Verify no overlap
    assert first_page_ids[0] != second_page_ids[0]
    assert second_page_ids[0] != third_page_ids[0]
    # IDs should be decreasing (ORDER BY id DESC)
    assert first_page_ids[0] > second_page_ids[0]
    assert second_page_ids[0] > third_page_ids[0]


def test_provider_log_non_admin_403(client, db, provider_user):
    """Non-admin (provider) hits endpoint -> 403."""
    # Authenticate as provider, not admin
    r_login = client.post("/auth/login", json={
        "email": provider_user.email,
        "password": "Test#2026",
    })
    assert r_login.status_code == 200
    provider_auth = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

    r = client.get(
        f"/admin/providers/{provider_user.id}/log",
        headers=provider_auth,
    )
    assert r.status_code == 403


def test_provider_log_unknown_provider_404(client, auth_header):
    """Unknown provider_id -> 404."""
    r = client.get(
        "/admin/providers/999/log",
        headers=auth_header,
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "Provider not found"
