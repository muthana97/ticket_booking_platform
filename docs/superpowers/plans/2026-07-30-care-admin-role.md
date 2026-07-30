# Care Admin Role (Restricted RBAC Tier) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a restricted admin tier — `role="care_admin"` — for customer-care agents. Read access to Providers / Trips / Bookings / Payments and per-provider audit log; write access to nothing except `POST /admin/payments/{id}/confirm`. Full admin manages care-admin accounts from the Settings hub.

**Architecture:** Zero migration for the primary role change (`User.role` is already `String`). One new dependency `require_admin_or_care` accepts both admin tiers. The router-level `dependencies=[Depends(require_admin)]` on `/admin/*` is removed and replaced with per-endpoint guards so read vs. write can vary. A tiny new `/admin/care-admins` router surface handles lifecycle (create / list / block / unblock; no deletion). Frontend uses `body.dataset.role` + two helpers (`isFullAdmin()` / `isCareAdmin()`) to hide tabs, buttons, and Settings sections.

**Tech Stack:** FastAPI + Pydantic v2 · SQLAlchemy ORM (Neon Postgres + SQLite in tests) · pytest 8.3 + FastAPI TestClient (in-memory SQLite / StaticPool / fresh engine per test) · Vanilla JS + pillow CSS (v2) inside `frontend/index.html`.

**Spec:** `docs/superpowers/specs/2026-07-30-care-admin-role-design.md`

## Global Constraints

- New role value on `User.role` is the exact string `"care_admin"`. No SQLAlchemy Enum in play; the column stays `Column(String, nullable=False, default="customer")`. Zero schema migration.
- Care admin accounts are always created with `status="active"` and `email_verified=True`. Full admin vouches at creation time; no OTP round-trip, no admin approval flow.
- Block is terminal (no deletion endpoint). Rationale: preserves `audit_events.actor_user_id` FK on payment confirmations recorded by that care admin.
- `require_admin` stays exactly as-is (rejects `care_admin` with 403 — desired for mutation-heavy endpoints).
- New dependency name: `require_admin_or_care`. Signature identical to `require_admin` except the accepted-role set is `("admin", "care_admin")`. Rejection detail string is the same as `require_admin`'s: `"Admin role required"`.
- Router-level `dependencies=[Depends(require_admin)]` on `/admin/*` is REMOVED as part of Task 1. Every endpoint that previously had no per-handler guard gets one added.
- Care admins are hidden from `GET /admin/providers` (they are not providers). They are surfaced only through `GET /admin/care-admins`.
- `POST /admin/care-admins` returns 409 on duplicate email against ANY role (customer, provider, existing admin, existing care admin).
- Password field on the create modal uses `type="password"` + `autocomplete="new-password"`.
- Frontend hiding is driven by `STATE.auth?.user?.role`. Never trust a client hint to unlock a mutation — every mutation is server-gated.
- Every new visible string gets both EN and AR entries.
- Follow pillow (v2) primitives only — `.pillow`, `.settings-section`, `.field-block`, `.cta`, `.status-pill`, `.modal-bg`, `.p-field`, `.p-input` are already established.
- No `--no-verify`, no `--amend`. One commit per task.

---

## File Structure

**Backend files touched:**
- Modify: `backend/src/auth/dependencies.py` — add `require_admin_or_care` function.
- Modify: `backend/src/admin/router.py` — remove router-level guard; add per-endpoint guards; swap the seven read/confirm endpoints to `require_admin_or_care`.
- Create: `backend/src/admin/care_admin_router.py` — new lifecycle router (`/admin/care-admins`).
- Create: `backend/src/admin/care_admin_service.py` — service layer for care admin CRUD.
- Modify: `backend/src/admin/schemas.py` — add `CareAdminCreate`, `CareAdminSummary` schemas.
- Modify: `backend/src/main.py` — one `app.include_router(care_admin_router)` line.
- Create: `backend/tests/admin/__init__.py` (empty, if not present).
- Create: `backend/tests/admin/test_care_admin_role.py` — auth-dependency + endpoint-gating tests.
- Create: `backend/tests/admin/test_care_admin_lifecycle.py` — CRUD tests.

**Frontend files touched:**
- Modify: `frontend/index.html` — new i18n keys (EN + AR), `paintChrome()` role branch, `isFullAdmin()` / `isCareAdmin()` helpers, tab-bar Reports hide, Provider Detail hide rules, Trip card button hides, Care Admin Accounts section markup + JS handlers.

Four tasks — backend gating → backend lifecycle → frontend hiding/branding → frontend management UI. Each has an independent reviewer gate.

---

## Task 1: Backend — care_admin role + require_admin_or_care + endpoint gating

**Files:**
- Modify: `backend/src/auth/dependencies.py` (add function after `require_admin` at line 65)
- Modify: `backend/src/admin/router.py:16` (remove router-level dependency) + lines 23-298 (per-endpoint guards)
- Create: `backend/tests/admin/__init__.py` (empty)
- Create: `backend/tests/admin/test_care_admin_role.py` (~200 lines, see Step 1)

**Interfaces:**
- Consumes: existing `get_current_user` dependency, existing `User` model (`role`, `status` columns), existing admin endpoints.
- Produces:
  - `require_admin_or_care(user: User = Depends(get_current_user)) -> User` — accepts `role in ("admin", "care_admin") and status == "active"`. Raises HTTPException(403, "Admin role required") otherwise. Used by all read-access admin endpoints plus `POST /admin/payments/{id}/confirm`.
  - Endpoint guards updated per the table in the spec (Section: Endpoint gating map).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/admin/__init__.py` as an empty file, then `backend/tests/admin/test_care_admin_role.py`:

```python
"""Care admin role acceptance + endpoint-gating tests.

Covers require_admin_or_care in isolation, then walks every admin
endpoint asserting the correct 200/403 for a care admin logged in.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password


# ----- fixtures -----

@pytest.fixture
def care_admin(db):
    """A care admin account. Active, email-verified, minted directly."""
    u = User(
        email="care@tazkirati.app", full_name="Care Agent",
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


@pytest.fixture
def blocked_care_admin(db):
    u = User(
        email="care-blocked@tazkirati.app", full_name="Blocked Agent",
        password_hash=hash_password("Test#2026"),
        role="care_admin", status="blocked", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


# ----- dependency-level tests -----

def test_require_admin_or_care_accepts_admin(client, auth_header):
    """Full admin passes require_admin_or_care — verified by hitting any
    endpoint that uses it (list bookings is one)."""
    r = client.get("/admin/bookings", headers=auth_header)
    assert r.status_code == 200, r.text


def test_require_admin_or_care_accepts_care_admin(client, care_auth):
    r = client.get("/admin/bookings", headers=care_auth)
    assert r.status_code == 200, r.text


def test_require_admin_or_care_rejects_customer(client, db):
    from src.auth.models import User
    u = User(
        email="cust@x.com", full_name="Cust Omer",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit()
    r = client.post("/auth/login", json={"email": u.email, "password": "Test#2026"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/admin/bookings", headers=headers)
    assert r.status_code == 403


def test_require_admin_or_care_rejects_provider(client, provider_user):
    r = client.post("/auth/login", json={
        "email": provider_user.email, "password": "Test#2026",
    })
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/admin/bookings", headers=headers)
    assert r.status_code == 403


def test_require_admin_or_care_rejects_blocked_care(client, blocked_care_admin):
    r = client.post("/auth/login", json={
        "email": blocked_care_admin.email, "password": "Test#2026",
    })
    # Login should succeed OR fail — either way subsequent /admin call is 403.
    # If login succeeds, get_current_user raises 403 for status=blocked.
    if r.status_code == 200:
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = client.get("/admin/bookings", headers=headers)
        assert r2.status_code == 403
    else:
        assert r.status_code == 403


def test_require_admin_or_care_rejects_unauth(client):
    r = client.get("/admin/bookings")
    assert r.status_code == 401


# ----- endpoint gating: care admin CAN reach these -----

def test_care_admin_can_view_providers(client, care_auth):
    r = client.get("/admin/providers", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_trips(client, care_auth):
    r = client.get("/admin/trips", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_bookings(client, care_auth):
    r = client.get("/admin/bookings", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_pending_payments(client, care_auth):
    r = client.get("/admin/payments/pending", headers=care_auth)
    assert r.status_code == 200, r.text


def test_care_admin_can_view_provider_log(client, care_auth, provider_user):
    r = client.get(f"/admin/providers/{provider_user.id}/log", headers=care_auth)
    assert r.status_code == 200, r.text


# ----- endpoint gating: care admin CANNOT reach these -----

def test_care_admin_cannot_approve_provider(client, care_auth, provider_user):
    r = client.post(f"/admin/providers/{provider_user.id}/approve", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_block_provider(client, care_auth, provider_user):
    r = client.post(f"/admin/providers/{provider_user.id}/block", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_toggle_capabilities(client, care_auth, provider_user):
    r = client.patch(
        f"/admin/providers/{provider_user.id}/capabilities",
        headers=care_auth, json={"can_add_trips": False},
    )
    assert r.status_code == 403


def test_care_admin_cannot_edit_trip(client, care_auth):
    # Any trip id will do — the auth gate fires before the row lookup.
    r = client.patch("/admin/trips/1", headers=care_auth, json={"price": 999})
    assert r.status_code == 403


def test_care_admin_cannot_delete_trip(client, care_auth):
    r = client.delete("/admin/trips/1", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_view_aggregate_reports(client, care_auth):
    r = client.get("/admin/reports", headers=care_auth)
    assert r.status_code == 403


def test_care_admin_cannot_view_provider_reports_drilldown(client, care_auth, provider_user):
    r = client.get(f"/admin/providers/{provider_user.id}/reports", headers=care_auth)
    assert r.status_code == 403


# ----- payment confirm (the one care admin mutation) -----

def test_care_admin_can_confirm_payment(client, care_auth, db):
    """Care admin can confirm a pending payment. Uses a seeded booking that
    has bill_generated_at set (Path B billing intent) so it's confirmable."""
    from src.auth.models import User
    from src.inventory.models import Trip
    from src.booking.models import Booking
    from datetime import datetime, timezone, timedelta

    # A provider + trip + committed_pending booking with a billing ref.
    prov = User(
        email="pconfirm@x.com", full_name="Pay Provider",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(prov); db.commit(); db.refresh(prov)
    trip = Trip(
        provider_id=prov.id, origin="Khartoum", destination="Port Sudan",
        departure_time=datetime.now(timezone.utc) + timedelta(days=3),
        price=100, seat_layout="45",
    )
    db.add(trip); db.commit(); db.refresh(trip)
    booking = Booking(
        trip_id=trip.id, status="committed_pending",
        total_price=100, channel="consumer",
        billing_ref="BOK-TEST-01",
        bill_generated_at=datetime.now(timezone.utc),
    )
    db.add(booking); db.commit(); db.refresh(booking)

    r = client.post(f"/admin/payments/{booking.id}/confirm", headers=care_auth)
    assert r.status_code == 200, r.text
```

**Note:** the `test_care_admin_can_confirm_payment` test may need small tweaks depending on the exact Booking columns required. Before writing implementation, run this test as-is and adjust field names to match the actual `Booking` model — grep `class Booking` in `backend/src/booking/models.py` if needed. The important assertion is `r.status_code == 200`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/admin/test_care_admin_role.py -v
```

Expected: ALL tests fail. Fixture-based tests fail at the login step (care admin role isn't yet accepted by the endpoint gates — care admin logs in fine, but every `/admin/*` call returns 403 from the current `require_admin`). Dependency-level test failures are proof that the endpoint gates today reject care_admin.

- [ ] **Step 3: Add the new dependency**

In `backend/src/auth/dependencies.py`, immediately after the existing `require_admin` function (currently at line 65):

```python
def require_admin_or_care(user: models.User = Depends(get_current_user)) -> models.User:
    """Accepts both `admin` and `care_admin`. Used on read-mostly admin
    endpoints plus POST /admin/payments/{id}/confirm — the one mutation
    the restricted care-admin tier is allowed to make."""
    if user.role not in ("admin", "care_admin") or user.status != "active":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
```

- [ ] **Step 4: Remove the router-level guard**

In `backend/src/admin/router.py:16`, change:

```python
router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])
```

To:

```python
router = APIRouter(prefix="/admin", tags=["Admin"])
```

The `require_admin` import at line 7 stays — several handlers still use it directly. Add a second import for the new dependency on the same line:

```python
from ..auth.dependencies import require_admin, require_admin_or_care
```

- [ ] **Step 5: Add per-endpoint guards to the five endpoints that lack them**

These endpoints today rely solely on the router-level guard; without an explicit per-handler dependency they'll now be unauthenticated. Add the correct guard to each.

At `backend/src/admin/router.py:23-29` (list_providers), add `admin=Depends(require_admin_or_care)` to the signature:

```python
@router.get("/providers", response_model=List[schemas.ProviderSummary])
def list_providers(
    status: Optional[str] = Query(default=None, regex="^(pending|active|blocked)$"),
    db: Session = Depends(get_db),
    admin=Depends(require_admin_or_care),
):
    """List provider users, optionally filtered by status."""
    return service.list_providers(db, status=status)
```

Same treatment for the other four endpoints without a per-handler guard:

- `@router.get("/trips", ...)` (~line 82) — add `admin=Depends(require_admin_or_care)` to signature.
- `@router.get("/bookings", ...)` (~line 184) — add `admin=Depends(require_admin_or_care)` to signature.
- `@router.get("/payments/pending", ...)` (~line 203) — add `admin=Depends(require_admin_or_care)` to signature.
- `@router.get("/reports", ...)` (~line 234) — add `admin=Depends(require_admin)` to signature (aggregate reports = full admin only).

Place the new kwarg at the end of each signature, matching the placement of `admin=Depends(...)` in the existing handlers that already have it.

- [ ] **Step 6: Swap guards on the three read/confirm endpoints that need widening**

- `@router.post("/payments/{booking_id}/confirm", ...)` at line 208-210: change `admin=Depends(require_admin)` → `admin=Depends(require_admin_or_care)`.
- `@router.get(...)` for `providers/{id}/log` at line 251-260: change `admin=Depends(require_admin)` → `admin=Depends(require_admin_or_care)`.

Endpoints keeping `require_admin` (no change): approve, block, capabilities, PATCH trips, DELETE trips, providers/{id}/reports.

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/admin/test_care_admin_role.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Run the full backend suite**

```bash
cd backend && python3 -m pytest -q
```

Expected: previously-passing tests still pass. Baseline was 191 after the provider Reports ship; expect 191 + N (N = number of tests in Step 1, ~19).

- [ ] **Step 9: Commit**

```bash
git add backend/src/auth/dependencies.py backend/src/admin/router.py backend/tests/admin/__init__.py backend/tests/admin/test_care_admin_role.py
git commit -m "$(cat <<'EOF'
feat(rbac): care_admin role + require_admin_or_care dependency

New auth dependency accepts role in ("admin", "care_admin"), used to
loosen guards on read-mostly admin endpoints plus the one mutation
care admins are allowed (POST /admin/payments/{id}/confirm).

Removes the router-level dependency on the /admin/* router — every
endpoint now carries an explicit per-handler guard so read vs write
can vary. Endpoints keeping require_admin: approve/block providers,
capability toggle, trip edit/delete, aggregate + per-provider reports.
Endpoints widened to require_admin_or_care: list providers, list
trips, list bookings, list/confirm payments, per-provider audit log.

Zero schema migration — User.role is already String, so "care_admin"
is a new accepted value without any ALTER.

19 new tests covering the dependency in isolation, every widened
endpoint (200 for care admin), and every unchanged endpoint (403 for
care admin).
EOF
)"
```

---

## Task 2: Backend — care admin lifecycle CRUD

**Files:**
- Modify: `backend/src/admin/schemas.py` — add `CareAdminCreate` (input) + `CareAdminSummary` (output) schemas.
- Create: `backend/src/admin/care_admin_service.py` — new service module.
- Create: `backend/src/admin/care_admin_router.py` — new router at `/admin/care-admins`.
- Modify: `backend/src/main.py` — include the new router.
- Create: `backend/tests/admin/test_care_admin_lifecycle.py` — CRUD tests.

**Interfaces:**
- Consumes: `hash_password` from `auth.utils`, existing `User` model, `require_admin` from `auth.dependencies`, existing `audit.service.record_event` seam.
- Produces:
  - `CareAdminCreate: {email: EmailStr, full_name: str (min 2 words), password: str (min 8)}`.
  - `CareAdminSummary: {id, email, full_name, status, created_at}`.
  - `POST /admin/care-admins` → 201 with `CareAdminSummary`. 409 on duplicate email (any role).
  - `GET /admin/care-admins` → `List[CareAdminSummary]`.
  - `POST /admin/care-admins/{id}/block` → `CareAdminSummary` (status="blocked").
  - `POST /admin/care-admins/{id}/unblock` → `CareAdminSummary` (status="active").
  - Audit events emitted: `care_admin_created`, `care_admin_blocked`, `care_admin_unblocked`. Payload includes `care_admin_id` and `care_admin_email`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/admin/test_care_admin_lifecycle.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python3 -m pytest tests/admin/test_care_admin_lifecycle.py -v
```

Expected: all fail with 404 (endpoints don't exist yet).

- [ ] **Step 3: Add the schemas**

In `backend/src/admin/schemas.py`, append at the end of the file. Match the existing schema style (Pydantic v2 with `model_config = ConfigDict(from_attributes=True)` for output shapes — grep for `from_attributes` in the file to confirm the exact pattern being used and match it):

```python
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime


class CareAdminCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def _at_least_two_words(cls, v: str) -> str:
        parts = v.strip().split()
        if len(parts) < 2:
            raise ValueError("full_name must contain at least two words")
        return " ".join(parts)


class CareAdminSummary(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
```

If the file already imports Pydantic pieces at the top, consolidate the imports there rather than re-importing at the end.

- [ ] **Step 4: Add the service layer**

Create `backend/src/admin/care_admin_service.py`:

```python
"""Care admin lifecycle service. Full-admin-only surface — endpoint-level
guards enforce that; this module trusts its callers on authorization.

Block is terminal (no delete): preserves audit_events.actor_user_id on
payment confirms recorded by the affected care admin.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..audit import service as audit_svc
from ..auth import models as auth_models
from ..auth.utils import hash_password
from . import schemas


def create_care_admin(
    db: Session, *, payload: schemas.CareAdminCreate, actor_user_id: int,
) -> auth_models.User:
    existing = db.query(auth_models.User).filter(
        auth_models.User.email == payload.email
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already in use")

    user = auth_models.User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role="care_admin",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    try:
        audit_svc.record_event(
            db,
            actor_user_id=actor_user_id,
            event_type="care_admin_created",
            payload={"care_admin_id": user.id, "care_admin_email": user.email},
        )
    except Exception as exc:
        # Non-fatal — matches Phase-1 audit-log pattern (nested SAVEPOINT
        # inside record_event; outer failure logs and moves on).
        import logging
        logging.getLogger(__name__).warning("[AUDIT] care_admin_created failed: %s", exc)

    return user


def list_care_admins(db: Session) -> list[auth_models.User]:
    return (
        db.query(auth_models.User)
        .filter(auth_models.User.role == "care_admin")
        .order_by(auth_models.User.created_at.desc())
        .all()
    )


def _load_care_admin(db: Session, care_admin_id: int) -> auth_models.User:
    user = (
        db.query(auth_models.User)
        .filter(
            auth_models.User.id == care_admin_id,
            auth_models.User.role == "care_admin",
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="Care admin not found")
    return user


def set_care_admin_status(
    db: Session, *, care_admin_id: int, new_status: str, actor_user_id: int,
) -> auth_models.User:
    assert new_status in ("active", "blocked")
    user = _load_care_admin(db, care_admin_id)
    user.status = new_status
    db.commit()
    db.refresh(user)

    event_type = "care_admin_blocked" if new_status == "blocked" else "care_admin_unblocked"
    try:
        audit_svc.record_event(
            db,
            actor_user_id=actor_user_id,
            event_type=event_type,
            payload={"care_admin_id": user.id, "care_admin_email": user.email},
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("[AUDIT] %s failed: %s", event_type, exc)

    return user
```

**Important:** verify `auth_models.User.created_at` actually exists on the User model before writing `order_by(User.created_at.desc())`. Grep `class User` in `backend/src/auth/models.py` to confirm; if the column is named something else (`created_at` is the convention but might be `registered_at` etc.), use whatever's there.

**Important:** verify the exact signature of `audit_svc.record_event`. Grep it in `backend/src/audit/service.py`. If the signature uses different keyword names (e.g. `event_type` vs `type`, `payload` vs `data`), adjust the calls above to match.

- [ ] **Step 5: Add the router**

Create `backend/src/admin/care_admin_router.py`:

```python
"""Care admin lifecycle router. Full-admin-only.

Provides create / list / block / unblock. No deletion by design (see
service module docstring for rationale).
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from . import care_admin_service, schemas


router = APIRouter(prefix="/admin/care-admins", tags=["Care Admins"])


@router.post("", response_model=schemas.CareAdminSummary, status_code=201)
def create_care_admin(
    payload: schemas.CareAdminCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.create_care_admin(
        db, payload=payload, actor_user_id=admin.id,
    )


@router.get("", response_model=List[schemas.CareAdminSummary])
def list_care_admins(
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.list_care_admins(db)


@router.post("/{care_admin_id}/block", response_model=schemas.CareAdminSummary)
def block_care_admin(
    care_admin_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.set_care_admin_status(
        db, care_admin_id=care_admin_id, new_status="blocked", actor_user_id=admin.id,
    )


@router.post("/{care_admin_id}/unblock", response_model=schemas.CareAdminSummary)
def unblock_care_admin(
    care_admin_id: int,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    return care_admin_service.set_care_admin_status(
        db, care_admin_id=care_admin_id, new_status="active", actor_user_id=admin.id,
    )
```

- [ ] **Step 6: Wire the router into the app**

In `backend/src/main.py`, find the `app.include_router(...)` block near the other admin router registrations. Add:

```python
from .admin.care_admin_router import router as care_admin_router
# ... (at the include_router block)
app.include_router(care_admin_router)
```

Match the exact import + include style already used for `admin.router` — grep for `admin.router` in `main.py` to confirm the pattern.

- [ ] **Step 7: Run the new tests to verify they pass**

```bash
cd backend && python3 -m pytest tests/admin/test_care_admin_lifecycle.py -v
```

Expected: all pass.

- [ ] **Step 8: Run the full backend suite**

```bash
cd backend && python3 -m pytest -q
```

Expected: previously-passing tests still pass. Baseline was 191 + 19 (Task 1) = 210. Expect 210 + 14 = 224.

- [ ] **Step 9: Commit**

```bash
git add backend/src/admin/schemas.py backend/src/admin/care_admin_service.py backend/src/admin/care_admin_router.py backend/src/main.py backend/tests/admin/test_care_admin_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(rbac): care admin lifecycle CRUD

Four new full-admin-only endpoints under /admin/care-admins: create,
list, block, unblock. No deletion by design — block is terminal so
audit_events.actor_user_id FK on payment confirms stays intact.

Create: 409 on duplicate email across ANY role (not just care admins);
full_name enforces GEN-1 at-least-two-words rule; password bcrypt-hashed
via existing hash_password. New care admin is minted active +
email_verified, so first sign-in works immediately.

List: filters to role="care_admin" only, ordered by created_at DESC.

Block/unblock: 404s if the id belongs to a non-care-admin. Blocked
account's still-valid JWT 403s on next request via existing
get_current_user guard.

Every lifecycle event emits an audit_events row (care_admin_created /
_blocked / _unblocked) using the Phase-1 nested-SAVEPOINT pattern so
an audit failure never breaks the underlying mutation.

14 new tests covering happy path, duplicate email (across roles),
name validation, role gating, 404 rules, and end-to-end block behavior.
EOF
)"
```

---

## Task 3: Frontend — role branding + tab-bar/surface hiding

**Files:**
- Modify: `frontend/index.html` — six discrete edits (i18n keys, `paintChrome()` role branch, `isFullAdmin()`/`isCareAdmin()` helpers, tab-bar Reports hide, Provider Detail hide rules, Trip card + Pending Payments buttons).

**Interfaces:**
- Consumes: `STATE.auth?.user?.role` from the existing login flow, existing `paintChrome()` / `applyLanguage()` / `t()` helpers.
- Produces:
  - `body.dataset.role === 'care_admin'` when the signed-in user is a care admin.
  - `#role-tag` text = "Care Admin" (EN) / "دعم العملاء" (AR).
  - Two new global helpers `isFullAdmin()` and `isCareAdmin()`, callable from any render function.
  - Reports tab hidden when `isCareAdmin()`.
  - Provider Detail hides Permissions section + per-provider Reports panel when `isCareAdmin()`.
  - Admin trip cards hide Edit + Delete buttons when `isCareAdmin()`.
  - Pending Payments Confirm button still renders for care admin.

- [ ] **Step 1: Add the EN + AR i18n key for the role label**

Locate the `I18N.en` and `I18N.ar` blocks in `frontend/index.html`. Grep for `role.admin` — you should find `role.admin: 'Admin'` (or similar) plus other role labels. Add adjacent:

EN block:
```javascript
    'role.care_admin': 'Care Admin',
```

AR block:
```javascript
    'role.care_admin': 'دعم العملاء',
```

- [ ] **Step 2: Extend `paintChrome()` to handle the care_admin role**

Grep for `paintChrome` in `frontend/index.html` and locate the section where it sets `body.dataset.role` and `#role-tag`. Currently the switch-like logic likely handles `customer` / `provider` / `admin` explicitly. Extend to include `care_admin`:

- `body.dataset.role = STATE.auth?.user?.role || ''` (probably already is that pattern — if it's a switch, add the case).
- `#role-tag` text: use `t('role.' + STATE.auth.user.role)` if the existing pattern already goes through `t()`; otherwise map explicitly.
- Care admin uses the SAME chrome as full admin (same topbar, same tab-bar shell) — no separate branch for the container-level DOM. Only tab/section contents differ.

If `paintChrome` also has role-specific tab-bar routing (e.g. `if (role === 'admin') showAdminTabBar()`), extend the same branch to trigger for `care_admin` too.

- [ ] **Step 3: Add the gating helpers**

Near where other STATE helpers live (grep for `STATE.auth` and find a helper cluster — probably near the top of the inline `<script>` block):

```javascript
const isFullAdmin = () => STATE.auth?.user?.role === 'admin';
const isCareAdmin = () => STATE.auth?.user?.role === 'care_admin';
```

Place them next to any existing `isProvider()`-style helpers if such helpers exist; otherwise near the STATE object definition.

- [ ] **Step 4: Hide the Reports tab for care admin**

Find the admin tab-bar render (grep for `admin-tab-reports` or the id of the Reports tab button). The button is likely rendered as part of a static tab-bar block. In the same JS site where `paintChrome()` or `refreshAdminTab()` runs, add:

```javascript
$('#admin-tab-reports').hidden = isCareAdmin();
```

If the currently-active tab was `reports` when a care admin somehow landed on it (e.g. stale route from a previous admin session), also fall back:

```javascript
if (isCareAdmin() && currentAdminTab === 'reports') {
  switchAdminTab('bookings');  // or whichever the default landing tab is
}
```

Grep for `currentAdminTab` and `switchAdminTab` to find the actual identifiers used.

- [ ] **Step 5: Hide Provider Detail Permissions + per-provider Reports for care admin**

Find the Provider Detail render function (grep `screen-admin-provider-detail` or `renderProviderDetail`). Locate the block that renders the Permissions section (four capability chips + approve/block buttons) and the per-provider Reports drilldown panel.

Wrap both sections' render / population code:

```javascript
if (isFullAdmin()) {
  // ... existing Permissions section render
}
```

And similarly for the per-provider Reports panel. If the sections are static HTML that always exists in the DOM, use `.hidden = isCareAdmin()` on the section containers instead.

- [ ] **Step 6: Hide Edit + Delete buttons on admin trip cards for care admin**

Find the admin Trips tab render (grep `admin-trip-card` or `renderAdminTrips`). Locate where Edit and Delete buttons are appended to each trip card. Guard both:

```javascript
if (isFullAdmin()) {
  // append Edit button
  // append Delete button
}
```

Manifest button stays visible for both tiers — do NOT guard that one.

- [ ] **Step 7: Verify Pending Payments Confirm button still renders for care admin**

Find the Pending Payments render (grep `payments-pending` or `renderPendingPayments`). The Confirm button should NOT be guarded by any role check — it's care admin's one power. If the existing render already has an `if (isFullAdmin())` guard around it (unlikely, but check), remove it.

- [ ] **Step 8: Hide the gear icon's Settings sections care admin shouldn't see**

Find `refreshAdminSettings` or the Settings hub render (grep `#settings-` or `admin-settings`). The hub is composed of `<section class="settings-section">` blocks. For care admin, hide:

- Commissions section (grep `#settings-commission-section` or similar).
- Care Admin Accounts section (doesn't exist yet — added in Task 4; leave the hide-when-care-admin scaffolding here so Task 4's markup naturally lands hidden).

Personal Information + Language stay visible.

```javascript
// Inside the Settings hub render/refresh
$('#settings-commission-section').hidden = !isFullAdmin();
$('#settings-care-admin-section')?.hidden = !isFullAdmin();  // Task 4 adds this
```

**Why `!isFullAdmin()` and not `isCareAdmin()`:** the negative form ("show only to full admins") is stricter — it also hides these sections from customers / providers who somehow land on the Settings screen. Care admin hiding falls out as a side effect. Defense in depth is cheap.

- [ ] **Step 9: JS syntax gate**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output.

- [ ] **Step 10: Backend regression check (should be unchanged — no backend touched)**

```bash
cd backend && python3 -m pytest -q
```

Expected: 224 passing (unchanged from Task 2 baseline).

- [ ] **Step 11: Manual smoke test — care admin sees the trimmed shell**

Serve the frontend against the deployed backend (or local). Sign in as admin, create a care admin account manually via the API (curl `POST /admin/care-admins` with any admin session — you can grab the bearer from the browser network tab), then sign out and sign back in as that care admin.

Verify:

1. Topbar role tag reads "Care Admin".
2. Admin tab-bar shows Providers / Trips / Bookings / Payments (four tabs); **Reports is hidden**.
3. Click Providers → list renders. Click a provider row → Provider Detail opens. Header + Activity Log visible; **Permissions section hidden**, **per-provider Reports drilldown hidden**.
4. Click Trips → list renders. Trip cards show Manifest button; **Edit + Delete hidden**.
5. Click Bookings → list renders.
6. Click Payments → pending list renders; **Confirm button visible**. Confirming one still works (payload lands, audit row records care admin as actor).
7. Click gear icon → Settings hub opens. Personal Information + Language sections visible; **Commissions section hidden**.

- [ ] **Step 12: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(v2): care admin role — chrome branding + surface hiding

paintChrome branches on role="care_admin" — same admin shell (topbar,
tab-bar container, gear icon), different contents. Role tag reads
"Care Admin" / "دعم العملاء". Two new global helpers (isFullAdmin /
isCareAdmin) drive per-surface hiding without scattering role strings
across render functions.

Hidden for care admin: Reports tab, Provider Detail Permissions
section + per-provider Reports panel, admin trip card Edit + Delete
buttons, Commissions section in Settings hub. Manifest button on
trip cards stays visible. Pending Payments Confirm button stays
enabled — care admin's one mutation.

If a care admin lands on the Reports tab (stale route from a
previous admin session), the switch drops them back to Bookings.
Every hide is UI-only — server enforcement is the source of truth
(see require_admin_or_care from the previous commit).

New EN + AR i18n key for role.care_admin.
EOF
)"
```

---

## Task 4: Frontend — Care Admin Accounts management UI in Settings hub

**Files:**
- Modify: `frontend/index.html` — five discrete edits (new Settings section markup, list render + row action wiring, create modal markup + submit handler, i18n keys, event wiring).

**Interfaces:**
- Consumes: `POST /admin/care-admins`, `GET /admin/care-admins`, `POST /admin/care-admins/{id}/block`, `POST /admin/care-admins/{id}/unblock` (Task 2), `isFullAdmin()` helper (Task 3), existing `api()`, `t()`, `$()`, `escapeHtml`, `fmtDate` (or whatever date formatter the codebase uses) helpers.
- Produces: new DOM ids `#settings-care-admin-section`, `#care-admin-list`, `#care-admin-empty`, `#care-admin-add-btn`, `#care-admin-create-modal`, `#ca-name`, `#ca-email`, `#ca-password`, `#ca-submit`; new JS functions `refreshCareAdmins()`, `renderCareAdminRows()`, `openCareAdminModal()`, `submitCareAdmin()`.

- [ ] **Step 1: Add the Settings section markup**

Find `<section class="settings-section" id="settings-commission-section">` (or whichever id the Commissions section uses — grep for it). Insert a new sibling section immediately above or below Commissions:

```html
<section class="settings-section" id="settings-care-admin-section" hidden>
  <div class="settings-head">
    <h3 data-i18n="settings.care_admin.title">Care Admin Accounts</h3>
    <button class="cta cta-inline" id="care-admin-add-btn"
            data-i18n="settings.care_admin.add_cta">+ Add care admin</button>
  </div>
  <p class="settings-lead" data-i18n="settings.care_admin.lead">
    Create limited-access admin accounts for customer care agents.
    They can view bookings, trips, providers, and confirm pending payments.
  </p>
  <div id="care-admin-list"></div>
  <div id="care-admin-empty" class="empty-state hidden"
       data-i18n="settings.care_admin.empty">
    No care admin accounts yet.
  </div>
</section>
```

The `hidden` attribute is default — Task 3 Step 8's `$('#settings-care-admin-section')?.hidden = !isFullAdmin()` removes it for full admins and keeps it hidden for everyone else.

- [ ] **Step 2: Add the create modal markup**

Find any existing modal in `frontend/index.html` (grep `modal-bg`) to see the exact primitive structure. Add a new modal:

```html
<div class="modal-bg" id="care-admin-create-modal">
  <div class="modal-card pillow">
    <h3 data-i18n="settings.care_admin.modal.title">New care admin</h3>
    <div class="field-block">
      <label data-i18n="settings.care_admin.modal.name">Full name</label>
      <input type="text" id="ca-name" maxlength="120"
             data-i18n-placeholder="settings.care_admin.modal.name.ph"
             placeholder="Two words minimum" />
    </div>
    <div class="field-block">
      <label data-i18n="settings.care_admin.modal.email">Email</label>
      <input type="email" id="ca-email" maxlength="120"
             autocomplete="off" />
    </div>
    <div class="field-block">
      <label data-i18n="settings.care_admin.modal.password">Password</label>
      <input type="password" id="ca-password" maxlength="128"
             autocomplete="new-password" />
    </div>
    <div class="modal-actions">
      <button class="btn-inline" onclick="closeCareAdminModal()"
              data-i18n="cancel">Cancel</button>
      <button class="cta" id="ca-submit"
              data-i18n="settings.care_admin.modal.submit">Create</button>
    </div>
  </div>
</div>
```

The exact class names (`modal-bg`, `modal-card`, `pillow`, `field-block`, `modal-actions`) MUST match those used by the existing modals in the file — grep for one modal (e.g. `trip-edit-modal` or `commission-override-modal`) and mirror its class structure so pillow theming lands automatically. Adjust if names differ.

- [ ] **Step 3: Add the JS handlers**

Place near the other Settings-hub refresh functions (grep for `refreshAdminSettings`):

```javascript
async function refreshCareAdmins() {
  if (!isFullAdmin()) return;
  try {
    const rows = await api('/admin/care-admins');
    renderCareAdminRows(rows);
  } catch (err) {
    console.error('refreshCareAdmins failed', err);
  }
}

function renderCareAdminRows(rows) {
  const list = $('#care-admin-list');
  const empty = $('#care-admin-empty');
  if (!rows || !rows.length) {
    list.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  list.innerHTML = rows.map(r => {
    const pill = r.status === 'active'
      ? `<span class="status-pill ok" data-i18n="settings.care_admin.status.active">Active</span>`
      : `<span class="status-pill danger" data-i18n="settings.care_admin.status.blocked">Blocked</span>`;
    const action = r.status === 'active'
      ? `<button class="btn-inline danger"
                 onclick="blockCareAdmin(${r.id})"
                 data-i18n="settings.care_admin.action.block">Block</button>`
      : `<button class="btn-inline ok"
                 onclick="unblockCareAdmin(${r.id})"
                 data-i18n="settings.care_admin.action.unblock">Unblock</button>`;
    return `<div class="admin-row pillow">
      <div class="ar-main">
        <div class="ar-name">${escapeHtml(r.full_name)}</div>
        <div class="ar-sub">${escapeHtml(r.email)}</div>
      </div>
      <div class="ar-meta">
        ${pill}
        ${action}
      </div>
    </div>`;
  }).join('');
  applyLanguage();  // re-translate the new [data-i18n] labels
}

function openCareAdminModal() {
  $('#ca-name').value = '';
  $('#ca-email').value = '';
  $('#ca-password').value = '';
  $('#care-admin-create-modal').classList.add('show');
  setTimeout(() => $('#ca-name').focus(), 0);
}

function closeCareAdminModal() {
  $('#care-admin-create-modal').classList.remove('show');
}

async function submitCareAdmin() {
  const name = $('#ca-name').value.trim();
  const email = $('#ca-email').value.trim();
  const password = $('#ca-password').value;
  // Client-side mirrors of the server rules (fail-fast UX).
  if (name.split(/\s+/).filter(Boolean).length < 2) {
    toast(t('settings.care_admin.err.name'));
    return;
  }
  if (!email || !password || password.length < 8) {
    toast(t('settings.care_admin.err.fields'));
    return;
  }
  try {
    await api('/admin/care-admins', {
      method: 'POST',
      body: JSON.stringify({ full_name: name, email, password }),
    });
    closeCareAdminModal();
    toast(t('settings.care_admin.toast.created'));
    refreshCareAdmins();
  } catch (err) {
    // api() typically parses {detail} — surface it as a toast.
    toast(err?.detail || t('settings.care_admin.err.create'));
  }
}

async function blockCareAdmin(id) {
  try {
    await api(`/admin/care-admins/${id}/block`, { method: 'POST' });
    toast(t('settings.care_admin.toast.blocked'));
    refreshCareAdmins();
  } catch (err) {
    toast(err?.detail || 'error');
  }
}

async function unblockCareAdmin(id) {
  try {
    await api(`/admin/care-admins/${id}/unblock`, { method: 'POST' });
    toast(t('settings.care_admin.toast.unblocked'));
    refreshCareAdmins();
  } catch (err) {
    toast(err?.detail || 'error');
  }
}
```

**Important:** verify `api()`, `toast()`, `escapeHtml`, `applyLanguage`, and `t()` all exist and match usage elsewhere in the file. Grep for each before writing. If `api()` takes the `{method, body}` object as the second argument, the calls above are correct (matches the existing `PATCH /admin/providers/{id}/capabilities` call site — grep to confirm). If not, adjust.

**Important:** verify the exact class names for row primitives (`admin-row pillow`, `ar-main`, `ar-name`, `ar-sub`, `ar-meta`) against the existing admin Providers-tab row markup — grep for `admin-row` in `frontend/index.html`. If different names are in use, mirror them so the pillow styling lands.

- [ ] **Step 4: Wire the "+ Add care admin" button + Settings refresh trigger**

Near where the other Settings-hub event handlers are wired (grep for `#settings-btn` or `refreshAdminSettings` click handler):

```javascript
$('#care-admin-add-btn')?.addEventListener('click', openCareAdminModal);
$('#ca-submit')?.addEventListener('click', submitCareAdmin);

// Backdrop click to dismiss (matches other modals — grep to confirm the pattern):
$('#care-admin-create-modal')?.addEventListener('click', (e) => {
  if (e.target.id === 'care-admin-create-modal') closeCareAdminModal();
});
```

Also ensure `refreshCareAdmins()` fires when the Settings hub is opened. Grep `refreshAdminSettings` — it's called on the gear-icon click and from `refreshDynamicScreen()`. Add:

```javascript
// Inside refreshAdminSettings() or the gear-icon handler
refreshCareAdmins();
```

- [ ] **Step 5: Add the EN i18n keys**

Locate the `I18N.en` block. Add:

```javascript
    'settings.care_admin.title': 'Care Admin Accounts',
    'settings.care_admin.lead': 'Create limited-access admin accounts for customer care agents. They can view bookings, trips, providers, and confirm pending payments.',
    'settings.care_admin.add_cta': '+ Add care admin',
    'settings.care_admin.empty': 'No care admin accounts yet.',
    'settings.care_admin.status.active': 'Active',
    'settings.care_admin.status.blocked': 'Blocked',
    'settings.care_admin.action.block': 'Block',
    'settings.care_admin.action.unblock': 'Unblock',
    'settings.care_admin.modal.title': 'New care admin',
    'settings.care_admin.modal.name': 'Full name',
    'settings.care_admin.modal.name.ph': 'Two words minimum',
    'settings.care_admin.modal.email': 'Email',
    'settings.care_admin.modal.password': 'Password',
    'settings.care_admin.modal.submit': 'Create',
    'settings.care_admin.err.name': 'Full name needs at least two words.',
    'settings.care_admin.err.fields': 'Fill every field. Password must be at least 8 characters.',
    'settings.care_admin.err.create': 'Could not create the care admin account.',
    'settings.care_admin.toast.created': 'Care admin created.',
    'settings.care_admin.toast.blocked': 'Care admin blocked.',
    'settings.care_admin.toast.unblocked': 'Care admin unblocked.',
```

- [ ] **Step 6: Add the AR i18n keys**

Locate the `I18N.ar` block. Add:

```javascript
    'settings.care_admin.title': 'حسابات دعم العملاء',
    'settings.care_admin.lead': 'أنشئ حسابات إدارية بصلاحيات محدودة لموظفي دعم العملاء. يمكنهم عرض الحجوزات والرحلات والمشغلين وتأكيد المدفوعات المعلقة.',
    'settings.care_admin.add_cta': '+ إضافة حساب دعم',
    'settings.care_admin.empty': 'لا توجد حسابات دعم عملاء بعد.',
    'settings.care_admin.status.active': 'نشط',
    'settings.care_admin.status.blocked': 'محظور',
    'settings.care_admin.action.block': 'حظر',
    'settings.care_admin.action.unblock': 'إلغاء الحظر',
    'settings.care_admin.modal.title': 'حساب دعم جديد',
    'settings.care_admin.modal.name': 'الاسم الكامل',
    'settings.care_admin.modal.name.ph': 'كلمتان على الأقل',
    'settings.care_admin.modal.email': 'البريد الإلكتروني',
    'settings.care_admin.modal.password': 'كلمة المرور',
    'settings.care_admin.modal.submit': 'إنشاء',
    'settings.care_admin.err.name': 'الاسم الكامل يجب أن يحتوي على كلمتين على الأقل.',
    'settings.care_admin.err.fields': 'املأ جميع الحقول. كلمة المرور 8 أحرف على الأقل.',
    'settings.care_admin.err.create': 'تعذّر إنشاء حساب الدعم.',
    'settings.care_admin.toast.created': 'تم إنشاء حساب الدعم.',
    'settings.care_admin.toast.blocked': 'تم حظر الحساب.',
    'settings.care_admin.toast.unblocked': 'تم إلغاء الحظر.',
```

- [ ] **Step 7: JS syntax gate**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output.

- [ ] **Step 8: Backend regression check (should be unchanged)**

```bash
cd backend && python3 -m pytest -q
```

Expected: 224 passing.

- [ ] **Step 9: Manual smoke test — full admin manages care admins**

Serve the frontend against the deployed backend. Sign in as admin, click the gear icon.

Verify:

1. Settings hub opens. Personal Information + Commissions + **Care Admin Accounts** sections visible. Language visible.
2. Care Admin Accounts section shows empty state ("No care admin accounts yet.").
3. Click "+ Add care admin". Modal opens with three inputs.
4. Try submit with a single-word name → toast "Full name needs at least two words." Modal stays open.
5. Try submit with an existing admin's email → toast "Email already in use" (or the server's exact detail).
6. Fill valid inputs: name "Care Agent One", email `care1@tazkirati.app`, password `CarePass#2026` → toast "Care admin created." Modal closes. Row appears with green "Active" pill + red "Block" button.
7. Click Block → row's pill flips to red "Blocked", button flips to green "Unblock".
8. Click Unblock → reverts.

- [ ] **Step 10: Manual smoke test — care admin uses the account**

Sign out. Sign in as `care1@tazkirati.app` / `CarePass#2026`.

Verify (this repeats Task 3's smoke checks — do them again to catch any regression from Task 4's markup):

1. Role tag reads "Care Admin".
2. Reports tab hidden. Four tabs only.
3. Provider Detail: Permissions + per-provider Reports hidden.
4. Trip cards: Edit + Delete hidden; Manifest visible.
5. Pending Payments Confirm button visible + working.
6. Gear icon → Settings hub: Care Admin Accounts section hidden (they can't manage each other), Commissions hidden. Personal Information + Language visible.

- [ ] **Step 11: Manual smoke test — Arabic**

While signed in as care admin, toggle language to Arabic. Confirm role tag reads "دعم العملاء" and every new visible string appears in Arabic.

- [ ] **Step 12: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(v2): Care Admin Accounts management UI in Settings hub

New pillow-styled section in the gear-icon Settings hub (visible only
to full admins) letting them mint care-admin accounts, view the roster,
and block/unblock. Create modal has three inputs (name, email, password
with autocomplete="new-password" to keep it out of the admin's browser
autofill). Client-side validation mirrors the server rules (name >= 2
words, password >= 8 chars) for fail-fast UX; every real check is
server-authoritative.

Row-level pillow surfaces with status pill + inline block/unblock
button. Row action buttons use existing danger / ok color tokens.
Empty state matches other Settings sections.

20 new EN + AR i18n keys under settings.care_admin.*. Section hidden
for both care admins themselves (they can't manage each other) and
non-admin visitors (defense in depth).

Care admin role feature complete end-to-end.
EOF
)"
```

---

## Verification (post-all-tasks)

- [ ] **Backend suite green**

```bash
cd backend && python3 -m pytest -q
```

Expected: 224 passing (was 191 before this plan; Task 1 adds ~19, Task 2 adds ~14).

- [ ] **Frontend JS syntax check**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output.

- [ ] **Deploy**

Push to `feat/mobile-scaffold` (Render auto-deploys). Wait for "Deploy live" in the Render dashboard.

- [ ] **Deployed smoke sweep**

Repeat Task 3 Step 11 + Task 4 Steps 9-11 against the live deployed URL. Focus items:

1. Care admin cannot mutate anything but a payment confirm (spot-check `PATCH /admin/trips/{id}` and `POST /admin/providers/{id}/approve` return 403).
2. Blocked care admin's still-valid JWT 403s on next request.
3. Care admin's payment confirmation shows the care admin as `actor_user_id` on the audit_events row (query the Neon DB directly or check the Provider Detail Activity Log if the affected trip belongs to one of the seeded providers).
4. Arabic mode: every new string translated.

- [ ] **Update CLAUDE.md**

Add a "Recent fixes" entry at the top of that section summarizing what shipped: the new role value, the endpoint gate split, the lifecycle CRUD surface, the frontend hiding rules, and the deliberate block-is-terminal / no-deletion decision.

```bash
git add claude.md
git commit -m "docs: log care admin RBAC tier ship in CLAUDE.md"
```
