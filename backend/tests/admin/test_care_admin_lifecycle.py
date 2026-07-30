"""Care admin lifecycle: create / list / block / unblock.

All four endpoints are full-admin-only. Care admins themselves cannot
manage each other.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password


@pytest.fixture
def care_admin(db):
    u = User(
        email="care-existing@tazkirati.app", full_name="Care Existing",
        password_hash=hash_password("Test#2026"),
        role="care_admin", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def care_auth(client, care_admin):
    r = client.post("/auth/login", json={
        "email": care_admin.email, "password": "Test#2026",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ----- create -----

def test_create_care_admin_happy_path(client, auth_header, db):
    r = client.post(
        "/admin/care-admins",
        headers=auth_header,
        json={
            "email": "new-care@tazkirati.app",
            "full_name": "New Care Agent",
            "password": "CarePass#2026",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "new-care@tazkirati.app"
    assert body["full_name"] == "New Care Agent"
    assert body["status"] == "active"
    assert "id" in body and "created_at" in body
    # Assert the row landed with the right role + hashed password
    from src.auth.models import User
    from src.auth.utils import verify_password
    row = db.query(User).filter(User.email == "new-care@tazkirati.app").first()
    assert row is not None
    assert row.role == "care_admin"
    assert row.status == "active"
    assert row.email_verified is True
    assert row.password_hash != "CarePass#2026"  # hashed
    assert verify_password("CarePass#2026", row.password_hash)


def test_create_care_admin_409_on_duplicate_email(client, auth_header, care_admin):
    r = client.post(
        "/admin/care-admins",
        headers=auth_header,
        json={
            "email": care_admin.email,  # already exists as care_admin
            "full_name": "Different Name",
            "password": "OtherPass#2026",
        },
    )
    assert r.status_code == 409


def test_create_care_admin_409_on_duplicate_email_across_roles(
    client, auth_header, provider_user,
):
    """Duplicate email check spans ALL roles, not just care admins."""
    r = client.post(
        "/admin/care-admins",
        headers=auth_header,
        json={
            "email": provider_user.email,  # a provider owns this email
            "full_name": "Fresh Name",
            "password": "FreshPass#2026",
        },
    )
    assert r.status_code == 409


def test_create_care_admin_short_name_422(client, auth_header):
    """Names must have at least 2 words (GEN-1)."""
    r = client.post(
        "/admin/care-admins",
        headers=auth_header,
        json={
            "email": "shortname@x.com",
            "full_name": "OneWord",
            "password": "Pass#2026",
        },
    )
    assert r.status_code == 422


def test_create_care_admin_requires_full_admin(client, care_auth):
    r = client.post(
        "/admin/care-admins",
        headers=care_auth,
        json={
            "email": "another@x.com",
            "full_name": "Another Care",
            "password": "Pass#2026",
        },
    )
    assert r.status_code == 403


def test_create_care_admin_requires_auth(client):
    r = client.post("/admin/care-admins", json={
        "email": "x@x.com", "full_name": "X Y", "password": "P#2026",
    })
    assert r.status_code == 401


# ----- list -----

def test_list_care_admins_returns_only_care_admins(
    client, auth_header, care_admin, admin_user, provider_user,
):
    r = client.get("/admin/care-admins", headers=auth_header)
    assert r.status_code == 200, r.text
    body = r.json()
    emails = {row["email"] for row in body}
    assert care_admin.email in emails
    assert admin_user.email not in emails
    assert provider_user.email not in emails


def test_list_care_admins_requires_full_admin(client, care_auth):
    r = client.get("/admin/care-admins", headers=care_auth)
    assert r.status_code == 403


# ----- block -----

def test_block_care_admin(client, auth_header, care_admin, db):
    r = client.post(
        f"/admin/care-admins/{care_admin.id}/block",
        headers=auth_header,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "blocked"
    from src.auth.models import User
    db.refresh(care_admin)
    assert care_admin.status == "blocked"


def test_block_care_admin_causes_next_request_403(
    client, auth_header, care_admin, care_auth,
):
    """End-to-end: block, then use the blocked account's still-valid JWT."""
    r = client.post(
        f"/admin/care-admins/{care_admin.id}/block",
        headers=auth_header,
    )
    assert r.status_code == 200
    # Blocked account's token no longer works.
    r2 = client.get("/admin/bookings", headers=care_auth)
    assert r2.status_code == 403


def test_block_requires_full_admin(client, care_auth, care_admin):
    r = client.post(
        f"/admin/care-admins/{care_admin.id}/block",
        headers=care_auth,
    )
    assert r.status_code == 403


def test_block_returns_404_for_missing_id(client, auth_header):
    r = client.post("/admin/care-admins/99999/block", headers=auth_header)
    assert r.status_code == 404


def test_block_rejects_non_care_admin_id(client, auth_header, provider_user):
    """Cannot block a provider through the care-admin block endpoint."""
    r = client.post(
        f"/admin/care-admins/{provider_user.id}/block",
        headers=auth_header,
    )
    assert r.status_code == 404


# ----- unblock -----

def test_unblock_care_admin(client, auth_header, care_admin, db):
    care_admin.status = "blocked"
    db.commit()
    r = client.post(
        f"/admin/care-admins/{care_admin.id}/unblock",
        headers=auth_header,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


def test_unblock_requires_full_admin(client, care_auth, care_admin):
    r = client.post(
        f"/admin/care-admins/{care_admin.id}/unblock",
        headers=care_auth,
    )
    assert r.status_code == 403
