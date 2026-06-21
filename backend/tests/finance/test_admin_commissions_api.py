from src.auth.models import User
from src.auth.utils import hash_password


def test_get_commissions_empty(client, auth_header):
    r = client.get("/admin/commissions", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body.get("global") is None
    assert body.get("overrides") == []


def test_put_global_inserts_then_updates(client, auth_header):
    r = client.put(
        "/admin/commissions/global",
        json={"rate_kind": "percentage", "rate_value": 8.0},
        headers=auth_header,
    )
    assert r.status_code == 200, r.text
    r2 = client.put(
        "/admin/commissions/global",
        json={"rate_kind": "flat_per_seat", "rate_value": 150.0},
        headers=auth_header,
    )
    assert r2.status_code == 200
    r3 = client.get("/admin/commissions", headers=auth_header)
    assert r3.json()["global"]["rate_kind"] == "flat_per_seat"


def test_put_global_validates_range(client, auth_header):
    r = client.put(
        "/admin/commissions/global",
        json={"rate_kind": "percentage", "rate_value": 150.0},
        headers=auth_header,
    )
    assert r.status_code == 400


def test_create_override_provider(client, auth_header, provider_user):
    r = client.post(
        "/admin/commissions/overrides",
        headers=auth_header,
        json={
            "scope": "provider",
            "provider_id": provider_user.id,
            "rate_kind": "percentage",
            "rate_value": 8.0,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider_name"] == provider_user.full_name


def test_create_override_duplicate_returns_409(client, auth_header, provider_user):
    payload = {
        "scope": "provider",
        "provider_id": provider_user.id,
        "rate_kind": "percentage",
        "rate_value": 8.0,
    }
    client.post("/admin/commissions/overrides", headers=auth_header, json=payload)
    r = client.post("/admin/commissions/overrides", headers=auth_header, json=payload)
    assert r.status_code == 409


def test_patch_override(client, auth_header, provider_user):
    r = client.post(
        "/admin/commissions/overrides",
        headers=auth_header,
        json={
            "scope": "provider",
            "provider_id": provider_user.id,
            "rate_kind": "percentage",
            "rate_value": 8.0,
        },
    )
    rid = r.json()["id"]
    r2 = client.patch(
        f"/admin/commissions/overrides/{rid}",
        headers=auth_header,
        json={"rate_kind": "percentage", "rate_value": 12.0},
    )
    assert r2.status_code == 200
    assert r2.json()["rate_value"] == 12.0


def test_delete_override(client, auth_header, provider_user):
    r = client.post(
        "/admin/commissions/overrides",
        headers=auth_header,
        json={
            "scope": "provider",
            "provider_id": provider_user.id,
            "rate_kind": "percentage",
            "rate_value": 8.0,
        },
    )
    rid = r.json()["id"]
    r2 = client.delete(f"/admin/commissions/overrides/{rid}", headers=auth_header)
    assert r2.status_code == 204


def test_non_admin_gets_403(client, db):
    u = User(
        email="cust@x.com", full_name="C",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u)
    db.commit()
    r = client.post("/auth/login", json={"email": "cust@x.com", "password": "Test#2026"})
    token = r.json()["access_token"]
    r2 = client.get(
        "/admin/commissions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 403
