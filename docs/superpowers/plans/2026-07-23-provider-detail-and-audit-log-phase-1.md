# Provider Detail Page + Audit Log (Phase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the audit-log infrastructure (`audit_events` table + emit sites at every mutation site + `GET /admin/providers/{id}/log` endpoint) and the new admin `screen-admin-provider-detail` page that consumes it — replacing the inline capability toggles + block/unblock buttons on the Admin → Providers tab with a dedicated per-provider detail page (header + permissions + activity log + reports drilldown).

**Architecture:** New `backend/src/audit/` module (mirrors `notifications/`, `finance/`) exposes `record_event(db, *, actor_user_id, provider_id, event_type, summary, ...)`. Each mutation site in `inventory/service.py`, `booking/service.py`, and `admin/service.py` calls it inside a nested savepoint so a bug in audit code can never break the underlying mutation, but a rolled-back mutation also rolls back the audit row (§5.4 of the spec). Frontend adds a new `screen-admin-provider-detail` in `frontend/index-v2.html` — Providers-tab rows become clickable, all per-provider controls move to the detail page.

**Tech Stack:** FastAPI + SQLAlchemy 2.x (session `begin_nested()` for savepoints), Pydantic v2, pytest 8.3 with in-memory SQLite `StaticPool` fixtures, vanilla-JS v2 SPA with the existing `I18N` runtime.

## Global Constraints

- **Only touch `frontend/index-v2.html`.** `frontend/index.html` is a rollback surface and must not be modified. (CLAUDE.md § "Constraints carried into v2")
- **Every new visible string gets both EN and AR keys** in the `I18N` table. Placeholders use `data-i18n-placeholder`. `summary` strings on log rows are DELIBERATELY English-only per spec §2 — no i18n on them.
- **All error-path `toast()` calls MUST pass `true` as the second arg** (isErr flag). File-wide convention (~30+ existing sites; violation surfaced in the last feature's Task 4 review).
- **`api()` wrapper signature is `api(path, {method, body: JSON.stringify(...)})`** — NOT `api(method, path, body)`.
- **Backend tests use fresh in-memory SQLite per test** via the existing `client` / `db` fixtures in `backend/tests/conftest.py`. Do NOT open real connections.
- **`record_event()` MUST use `db.begin_nested()` (SAVEPOINT)** so a failed audit insert never poisons the caller's outer transaction. This is a hard correctness requirement from spec §5.4.
- **`record_event()` MUST NOT raise.** Wrap in try/except; log the exception via `print("[AUDIT] ...")`; return silently. Missing log entry > broken mutation.
- **`provider_id` on the audit row is denormalized.** Even after the target trip is deleted, the row still knows which provider it belonged to.
- **Working directory** for all commands: `/Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform`. Backend tests run from `backend/` with `cd backend && ./venv/bin/pytest ...`.
- **Screen registered in `PILLOW_SCREENS`** JS Set — otherwise the new screen renders with v1 legacy CSS. (Learned from the last feature's Task 4.)
- **Screen registered in the CSS `body[data-screen="..."]` visibility chain** near line 800 in `frontend/index-v2.html`.
- **No changes to `backend/src/booking/tasks.py`** — the Reaper is golden per CLAUDE.md.
- **No new dependencies.** SQLAlchemy `begin_nested()` and Postgres/SQLite JSONB/JSON types are already available.

---

## File Structure

**Backend files to create:**
- `backend/src/audit/__init__.py` — empty package marker
- `backend/src/audit/models.py` — `AuditEvent` SQLAlchemy model
- `backend/src/audit/service.py` — `record_event()` + `query_log()` + helpers
- `backend/src/audit/schemas.py` — Pydantic response schemas (`AuditEventItem`, `AuditLogResponse`, `AuditActor`)
- `backend/tests/audit/__init__.py` — empty
- `backend/tests/audit/test_record_event.py` — savepoint + rollback + swallow tests
- `backend/tests/audit/test_query_log.py` — filter + pagination + auth tests

**Backend files to modify:**
- `backend/src/database.py` — import `audit.models` so `Base.metadata` sees the new table
- `backend/tests/conftest.py` — same import so `create_all()` builds the table in the test DB
- `backend/src/inventory/service.py` — thread `actor_user_id` through `create_trip`, `update_trip`, `delete_trip`; call `record_event()`
- `backend/src/inventory/router.py` — pass `current_user.id` into service calls
- `backend/src/admin/router.py` — pass `current_user.id` into service calls for admin trip routes; add new endpoints
- `backend/src/admin/service.py` — thread `actor_user_id` through `set_provider_status`, `update_provider_capabilities`, `confirm_payment`; call `record_event()`
- `backend/src/booking/service.py` — thread `actor_user_id` through `lock_seats`, `mint_billing_intent`, `provider_confirm`; call `record_event()`
- `backend/src/booking/router.py` — pass `current_user.id` into service calls

**Frontend file to modify:**
- `frontend/index-v2.html` — new screen `#screen-admin-provider-detail`, modify `renderAdminProviders`, add `renderProviderDetail`, `renderAuditLog`, filter handlers, i18n keys

**Docs to modify:**
- `claude.md` — Recent Fixes entry; deferred section updated (audit log partially shipped)

---

## Task 1: `audit_events` schema + `record_event()` + `query_log()` service

**Files:**
- Create: `backend/src/audit/__init__.py` (empty)
- Create: `backend/src/audit/models.py`
- Create: `backend/src/audit/service.py`
- Create: `backend/src/audit/schemas.py`
- Modify: `backend/src/database.py` (import for schema registration)
- Modify: `backend/tests/conftest.py` (import for test-DB schema)
- Create: `backend/tests/audit/__init__.py` (empty)
- Create: `backend/tests/audit/test_record_event.py`

**Interfaces produced (later tasks consume):**
- `audit.service.record_event(db, *, actor_user_id: int, provider_id: int, event_type: str, summary: str, target_type: str | None = None, target_id: int | None = None, metadata: dict | None = None) -> None`
- `audit.service.query_log(db, *, provider_id: int, q: str | None = None, event_type: str | None = None, from_ts: datetime | None = None, to_ts: datetime | None = None, limit: int = 100, before_id: int | None = None) -> tuple[list[audit.models.AuditEvent], int | None]` — returns `(items, next_before_id)`
- `audit.schemas.AuditEventItem`, `AuditLogResponse`, `AuditActor`
- `audit.models.AuditEvent` (SQLAlchemy)

- [ ] **Step 1: Create the package structure + failing tests**

```bash
mkdir -p backend/src/audit backend/tests/audit
touch backend/src/audit/__init__.py backend/tests/audit/__init__.py
```

Create `backend/tests/audit/test_record_event.py`:

```python
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.audit import service as audit_svc, models as audit_models
from src.auth import models as auth_models
from src.auth.utils import hash_password


def _seed_admin_and_provider(db):
    admin = auth_models.User(
        email="a@x.com", password_hash=hash_password("x"), full_name="Admin A",
        role="admin", status="active", email_verified=True,
    )
    prov = auth_models.User(
        email="p@x.com", password_hash=hash_password("x"), full_name="Prov P",
        role="provider", status="active", email_verified=True,
    )
    db.add_all([admin, prov]); db.commit(); db.refresh(admin); db.refresh(prov)
    return admin, prov


def test_record_event_inserts_row(db):
    admin, prov = _seed_admin_and_provider(db)
    audit_svc.record_event(
        db,
        actor_user_id=admin.id,
        provider_id=prov.id,
        event_type="trip_edited",
        summary="Admin A edited trip #47: price 500→600",
        target_type="trip",
        target_id=47,
        metadata={"before": {"price": 500}, "after": {"price": 600}},
    )
    db.commit()
    rows = db.query(audit_models.AuditEvent).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == admin.id
    assert row.provider_id == prov.id
    assert row.event_type == "trip_edited"
    assert row.summary.startswith("Admin A edited")
    assert row.target_type == "trip"
    assert row.target_id == 47
    assert row.metadata_ == {"before": {"price": 500}, "after": {"price": 600}}


def test_record_event_rolls_back_with_outer_transaction(db):
    """If the caller rolls back, the audit row must roll back too — spec §5.4."""
    admin, prov = _seed_admin_and_provider(db)
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    db.rollback()
    assert db.query(audit_models.AuditEvent).count() == 0


def test_record_event_swallows_exception(db, monkeypatch):
    """A bug in the audit code must NEVER break the caller.

    We force db.add to raise, then call record_event. It must not propagate."""
    admin, prov = _seed_admin_and_provider(db)

    real_add = db.add
    calls = {"add": 0}

    def _boom(obj):
        calls["add"] += 1
        # Only blow up on AuditEvent inserts; leave the seeded user alone.
        if isinstance(obj, audit_models.AuditEvent):
            raise RuntimeError("simulated audit failure")
        return real_add(obj)

    monkeypatch.setattr(db, "add", _boom)

    # Must not raise.
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    # And the outer session must still be usable for the caller's own commit.
    monkeypatch.setattr(db, "add", real_add)
    db.add(auth_models.User(
        email="post@x.com", password_hash=hash_password("x"), full_name="Post",
        role="customer", status="active", email_verified=True,
    ))
    db.commit()  # must not raise
    assert db.query(auth_models.User).filter_by(email="post@x.com").count() == 1


def test_record_event_savepoint_isolates_failure(db, monkeypatch):
    """Even when the audit insert fails, the SAVEPOINT protects the outer
    transaction — subsequent SQL in the same session still works."""
    admin, prov = _seed_admin_and_provider(db)

    # Simulate a broken audit insert
    def _bad_flush():
        raise RuntimeError("simulated flush failure")

    original_flush = db.flush

    def _flush_when_audit_pending(*a, **kw):
        pending = [o for o in db.new if isinstance(o, audit_models.AuditEvent)]
        if pending:
            raise RuntimeError("simulated audit flush failure")
        return original_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_when_audit_pending)
    audit_svc.record_event(
        db, actor_user_id=admin.id, provider_id=prov.id,
        event_type="test", summary="s",
    )
    # Session is not poisoned:
    monkeypatch.setattr(db, "flush", original_flush)
    prov.full_name = "New Name"
    db.commit()
    db.refresh(prov)
    assert prov.full_name == "New Name"
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd backend && ./venv/bin/pytest tests/audit/ -v
```
Expected: All 4 fail with `ModuleNotFoundError: No module named 'src.audit'` (or `audit.models`).

- [ ] **Step 3: Create `backend/src/audit/models.py`**

```python
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from ..database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=True)
    target_id = Column(Integer, nullable=True)
    summary = Column(Text, nullable=False)
    # Use JSONB on Postgres, JSON on SQLite. `metadata` is a reserved
    # SQLAlchemy attribute name (Declarative.metadata), so store under
    # metadata_ Python-side, exposed via .metadata_ everywhere.
    metadata_ = Column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_events_provider_created", "provider_id", "created_at"),
        Index(
            "ix_audit_events_provider_type_created",
            "provider_id",
            "event_type",
            "created_at",
        ),
    )
```

- [ ] **Step 4: Create `backend/src/audit/service.py`**

```python
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models


def record_event(
    db: Session,
    *,
    actor_user_id: int,
    provider_id: int,
    event_type: str,
    summary: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Emit an audit event inside the caller's transaction.

    Uses a SAVEPOINT (nested transaction) so a failed insert rolls back only
    the savepoint — the caller's outer transaction stays clean. Any exception
    is swallowed and logged; the audit layer must NEVER break a mutation.

    Does NOT commit the outer transaction — the caller's own commit (or
    rollback) determines whether the audit row lands.
    """
    try:
        with db.begin_nested():
            db.add(models.AuditEvent(
                actor_user_id=actor_user_id,
                provider_id=provider_id,
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                metadata_=metadata,
            ))
    except Exception as e:  # noqa: BLE001 — intentional broad catch
        print(f"[AUDIT] record_event failed silently: {e!r}")


def query_log(
    db: Session,
    *,
    provider_id: int,
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    limit: int = 100,
    before_id: Optional[int] = None,
) -> tuple[list[models.AuditEvent], Optional[int]]:
    """Return (items, next_before_id). next_before_id is None when done."""
    limit = min(max(1, int(limit)), 500)
    query = db.query(models.AuditEvent).filter(models.AuditEvent.provider_id == provider_id)
    if q:
        query = query.filter(models.AuditEvent.summary.ilike(f"%{q}%"))
    if event_type:
        query = query.filter(models.AuditEvent.event_type == event_type)
    if from_ts:
        query = query.filter(models.AuditEvent.created_at >= from_ts)
    if to_ts:
        query = query.filter(models.AuditEvent.created_at <= to_ts)
    if before_id is not None:
        query = query.filter(models.AuditEvent.id < before_id)

    rows = query.order_by(models.AuditEvent.id.desc()).limit(limit + 1).all()

    if len(rows) > limit:
        next_before = rows[limit - 1].id
        rows = rows[:limit]
    else:
        next_before = None
    return rows, next_before
```

- [ ] **Step 5: Create `backend/src/audit/schemas.py`**

```python
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditActor(BaseModel):
    id: int
    full_name: str
    role: str


class AuditEventItem(BaseModel):
    id: int
    event_type: str
    actor: AuditActor
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    summary: str
    metadata: Optional[dict[str, Any]] = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    items: list[AuditEventItem]
    next_before_id: Optional[int] = None
```

- [ ] **Step 6: Register the model with `Base.metadata`**

Modify `backend/tests/conftest.py`. Find the block of `import` statements that ensures each model file is loaded before `Base.metadata.create_all(bind=eng)`:

```python
    from src.database import Base
    import src.auth.models  # noqa: F401
    import src.inventory.models  # noqa: F401
    import src.booking.models  # noqa: F401
    import src.finance.models  # noqa: F401
    import src.notifications.models  # noqa: F401
    import src.promo.models  # noqa: F401
```

Append:
```python
    import src.audit.models  # noqa: F401
```

Also add the same import in `backend/src/main.py` where `_ensure_schema()` imports models before `create_all`. Grep for `import src.notifications.models` there; add the audit import alongside.

- [ ] **Step 7: Run the audit tests to confirm they pass**

```bash
cd backend && ./venv/bin/pytest tests/audit/test_record_event.py -v
```
Expected: All 4 PASS.

- [ ] **Step 8: Run the full backend suite for regressions**

```bash
cd backend && ./venv/bin/pytest -q
```
Expected: All existing tests still pass. Suite grows by 4 (140 → 144).

- [ ] **Step 9: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/audit/ backend/tests/audit/ backend/tests/conftest.py backend/src/main.py
git commit -m "$(cat <<'EOF'
feat(audit): audit_events table + record_event() + query_log()

New backend/src/audit/ module providing the schema + service layer for
Phase 1 of the provider-detail feature. record_event() uses a nested
SAVEPOINT so a bad audit insert can never break the underlying mutation
transaction; failures are logged via [AUDIT] print and swallowed.
query_log() supports keyword ILIKE + event_type + date range + cursor
pagination via (id < before_id) ORDER BY id DESC.

Schema auto-lands via existing _ensure_schema() / test conftest
import chain — no manual migration on Render.

4 new tests covering insert, outer-rollback participation, exception
swallowing, and savepoint isolation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Emit sites in `inventory/service.py` (trip create/edit/delete)

**Files:**
- Modify: `backend/src/inventory/service.py`
- Modify: `backend/src/inventory/router.py`
- Modify: `backend/src/admin/router.py`
- Create: `backend/tests/audit/test_inventory_emit_sites.py`

**Interfaces consumed:** `audit.service.record_event` from Task 1.

**Interfaces produced (later tasks consume):** none — this task just adds calls to existing service functions.

The three inventory service functions (`create_trip`, `update_trip`, `delete_trip`) currently take no `actor_user_id` because they only received `provider_id` (which for creates equals the actor, but for admin edits/deletes doesn't). Add a required `actor_user_id: int` keyword-only parameter to each and thread it from both routers.

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/audit/test_inventory_emit_sites.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && ./venv/bin/pytest tests/audit/test_inventory_emit_sites.py -v
```
Expected: All 6 fail — no audit rows exist because emit sites aren't wired yet.

- [ ] **Step 3: Add `actor_user_id` parameter to inventory service functions + emit calls**

In `backend/src/inventory/service.py`, at the top of the file, add:
```python
from ..audit import service as audit_svc
```

**Modify `create_trip`** — add keyword-only `actor_user_id: int` (place it after `provider_id`):

```python
def create_trip(
    db: Session,
    *,
    origin: str,
    destination: str,
    total_seats: int,
    departure_time: datetime,
    price: float,
    provider_id: int,
    actor_user_id: int,
) -> models.Trip:
```

At the very end of `create_trip`, just BEFORE the `return trip` (which itself is right after `db.commit()`), add:
```python
    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=provider_id,
        event_type="trip_created",
        target_type="trip",
        target_id=trip.id,
        summary=(
            f"{route.origin} → {route.destination} · "
            f"{trip.departure_time.strftime('%Y-%m-%d %H:%M')} · "
            f"{total_seats}-seater · SDG {price:.0f}"
        ),
        metadata={
            "origin": route.origin,
            "destination": route.destination,
            "departure_time": trip.departure_time.isoformat(),
            "price": float(price),
            "total_seats": total_seats,
        },
    )
    db.commit()
    return trip
```

Note: the existing function already commits before we add this. We need `trip.id` to be set (requires the first commit or a `db.flush()`). Read the existing function body carefully — if the current commit ordering means `trip.id` is populated before the audit call, we're fine. If not, replace the pre-existing `db.commit()` with `db.flush()`, add the audit call, then `db.commit()` once at the end.

**Modify `update_trip`** — add keyword-only `actor_user_id: int`:

```python
def update_trip(
    db: Session,
    *,
    trip_id: int,
    price: float | None = None,
    departure_time: "datetime | None" = None,
    actor_user_id: int,
) -> tuple[models.Trip, dict]:
```

Locate `if delta: db.commit()`. Replace with:
```python
    if delta:
        audit_svc.record_event(
            db,
            actor_user_id=actor_user_id,
            provider_id=trip.provider_id,
            event_type="trip_edited",
            target_type="trip",
            target_id=trip.id,
            summary=_format_trip_edit_summary(db, actor_user_id, trip.id, delta),
            metadata={"before": {k: v["from"] for k, v in delta.items()},
                       "after":  {k: v["to"]   for k, v in delta.items()}},
        )
        db.commit()
        db.refresh(trip)
```

Where `_format_trip_edit_summary` is a small helper added at the top of the file:
```python
def _format_trip_edit_summary(db: Session, actor_user_id: int, trip_id: int, delta: dict) -> str:
    from ..auth import models as auth_models
    actor = db.query(auth_models.User).filter_by(id=actor_user_id).first()
    actor_label = f"{actor.full_name} ({actor.role})" if actor else f"user #{actor_user_id}"
    parts = []
    if "price" in delta:
        parts.append(f"price {delta['price']['from']:.0f}→{delta['price']['to']:.0f}")
    if "departure_time" in delta:
        parts.append(
            f"departure {delta['departure_time']['from'].strftime('%m-%d %H:%M')}"
            f"→{delta['departure_time']['to'].strftime('%m-%d %H:%M')}"
        )
    change_text = ", ".join(parts)
    return f"{actor_label} edited trip #{trip_id}: {change_text}"
```

**Modify `delete_trip`** — add keyword-only `actor_user_id: int`:

```python
def delete_trip(db: Session, *, trip_id: int, actor_user_id: int) -> None:
```

Just BEFORE the final `db.commit()` in the function, snapshot the trip data (before it's gone) and emit:
```python
    from ..auth import models as auth_models
    actor = db.query(auth_models.User).filter_by(id=actor_user_id).first()
    actor_label = f"{actor.full_name} ({actor.role})" if actor else f"user #{actor_user_id}"
    route = trip.route  # relationship loaded already
    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=trip.provider_id,
        event_type="trip_deleted",
        target_type="trip",
        target_id=trip.id,
        summary=(
            f"{actor_label} deleted trip #{trip.id} "
            f"({route.origin} → {route.destination}, "
            f"{trip.departure_time.strftime('%Y-%m-%d %H:%M')})"
        ),
        metadata={
            "origin": route.origin,
            "destination": route.destination,
            "departure_time": trip.departure_time.isoformat(),
            "price": float(trip.price),
        },
    )
```

- [ ] **Step 4: Update routers to pass `actor_user_id`**

**`backend/src/inventory/router.py`**: find every call to `service.create_trip`, `service.update_trip`, `service.delete_trip`. Add `actor_user_id=current_user.id` to each. Grep to be sure you get them all (`service\.\(create\|update\|delete\)_trip`).

**`backend/src/admin/router.py`**: same treatment for the admin path calls (lines ~158 and ~170 per earlier read).

- [ ] **Step 5: Run inventory emit tests + full suite**

```bash
cd backend && ./venv/bin/pytest tests/audit/test_inventory_emit_sites.py -v
cd backend && ./venv/bin/pytest -q
```
Expected: 6 new tests pass; full suite green. Suite: 144 → 150.

- [ ] **Step 6: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/inventory/ backend/src/admin/router.py backend/tests/audit/test_inventory_emit_sites.py
git commit -m "$(cat <<'EOF'
feat(audit): emit trip_created / trip_edited / trip_deleted events

Threads actor_user_id through create_trip / update_trip / delete_trip
and calls audit.service.record_event at each mutation site. Same
service functions serve both the provider path (/trips) and the admin
path (/admin/trips) — the actor distinguishes.

Summary strings are pre-rendered at emit time ("Alice (admin) edited
trip #47: price 500→600"), matching spec §4.

6 new integration tests covering provider + admin paths for all three
actions, plus a rolled-back-mutation-leaves-no-audit-row check.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Emit sites in `admin/service.py` (approve / block / capabilities / payment confirm)

**Files:**
- Modify: `backend/src/admin/service.py`
- Modify: `backend/src/admin/router.py`
- Create: `backend/tests/audit/test_admin_emit_sites.py`

**Interfaces consumed:** `audit.service.record_event`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/audit/test_admin_emit_sites.py`:

```python
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
    """Requires an existing committed_pending booking to confirm.

    Reuse the booking-flow helper conventions from
    backend/tests/booking/test_confirm_path_snapshots_commission.py — that
    file already creates a trip, locks seats, mints billing, then admin-
    confirms. Follow the same seed pattern here; the assertion is on the
    audit_events row that lands after confirm_payment."""
    # See test_confirm_path_snapshots_commission.py for a working setup that
    # gets a booking to committed_pending. Copy the fixture / helper for a
    # minimal repro here.
    pytest_skip_msg = (
        "Copy the setup from tests/booking/test_confirm_path_snapshots_commission.py "
        "to create a committed_pending booking, then admin-confirms it, then "
        "asserts an audit_events row with event_type='payment_confirmed', "
        "actor_user_id=admin.id, provider_id=<trip's provider_id>."
    )
    import pytest
    pytest.skip(pytest_skip_msg)
```

The `test_payment_confirm_emits_payment_confirmed` test is intentionally skipped in the plan pending implementation — the setup for a `committed_pending` booking is nontrivial and lives in an existing test file. The subagent implementing this task should copy that setup (or invoke a shared helper if one exists) and unskip.

- [ ] **Step 2: Run tests to confirm they fail (or skip)**

```bash
cd backend && ./venv/bin/pytest tests/audit/test_admin_emit_sites.py -v
```
Expected: 4 fail + 1 skip.

- [ ] **Step 3: Modify `admin/service.py` — thread actor + emit**

At the top of the file, add:
```python
from ..audit import service as audit_svc
```

**Modify `set_provider_status`** — add `actor_user_id: int`:

```python
def set_provider_status(
    db: Session, *, provider_id: int, new_status: str, actor_user_id: int,
) -> auth_models.User:
```

After `db.commit(); db.refresh(user)`, before the final `print(...)`, add:
```python
    # Determine event_type: pending → active = approved; blocked → active =
    # unblocked; any → blocked = blocked. Kept as 3 distinct event types so
    # the UI can pick different icons.
    prior_status_map = {"pending": "provider_approved", "blocked": "provider_unblocked"}
    if new_status == "active":
        event_type = prior_status_map.get(previous_status, "provider_approved")
    elif new_status == "blocked":
        event_type = "provider_blocked"
    else:
        event_type = "provider_status_changed"

    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=user.id,
        event_type=event_type,
        target_type="provider",
        target_id=user.id,
        summary=f"Provider {user.full_name} → {new_status}",
        metadata={"from": previous_status, "to": new_status},
    )
    db.commit()
```

You'll need to capture `previous_status` BEFORE the `user.status = new_status` assignment. Insert `previous_status = user.status` right before that line.

**Modify `update_provider_capabilities`** — add `actor_user_id: int`. After the existing `notif.create_notification` loop, in the `if changed:` block, emit one audit event per flag flipped:

```python
        for key, value in changed.items():
            audit_svc.record_event(
                db,
                actor_user_id=actor_user_id,
                provider_id=user.id,
                event_type="capability_changed",
                target_type="capability",
                target_id=None,
                summary=(
                    f"Capability {key} {'enabled' if value else 'disabled'} "
                    f"for {user.full_name}"
                ),
                metadata={"capability": key, "to": bool(value)},
            )
        db.commit()
```

**Modify `confirm_payment`** — add `actor_user_id: int`. Just before the function's final return, add:
```python
    audit_svc.record_event(
        db,
        actor_user_id=actor_user_id,
        provider_id=trip.provider_id,
        event_type="payment_confirmed",
        target_type="booking",
        target_id=booking.id,
        summary=(
            f"Payment confirmed for booking {booking.billing_reference} "
            f"(SDG {float(booking.total_price):.0f})"
        ),
        metadata={"amount": float(booking.total_price)},
    )
    db.commit()
```

You'll need `trip` in scope — either it's already there (grep), or add a lookup.

- [ ] **Step 4: Update `admin/router.py`**

For each of `set_provider_status`, `update_provider_capabilities`, `confirm_payment` calls in the router, add `actor_user_id=current_user.id`. Grep for the service function names to find them.

- [ ] **Step 5: Unskip the payment-confirm test**

Rewrite `test_payment_confirm_emits_payment_confirmed` using the setup pattern from `backend/tests/booking/test_confirm_path_snapshots_commission.py`. Assert the audit row lands with the expected fields.

- [ ] **Step 6: Run admin emit tests + full suite**

```bash
cd backend && ./venv/bin/pytest tests/audit/test_admin_emit_sites.py -v
cd backend && ./venv/bin/pytest -q
```
Expected: 5 new tests pass; suite green. Suite: 150 → 155.

- [ ] **Step 7: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/admin/ backend/tests/audit/test_admin_emit_sites.py
git commit -m "$(cat <<'EOF'
feat(audit): emit provider_* + capability_changed + payment_confirmed

Threads actor_user_id through admin.service.set_provider_status,
update_provider_capabilities, and confirm_payment. Emits one audit
row per action, per capability flag, and per confirmed payment.

status transitions are broken out into three event_types
(provider_approved / provider_blocked / provider_unblocked) so the UI
can pick distinct icons; capability flips emit one row per flag with
metadata {"capability": key, "to": bool}.

5 new integration tests (was skipped for payment_confirmed until the
committed_pending setup lands here from the existing confirm-path
test file).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Emit sites in `booking/service.py` (lock_seats / mint_billing / provider_confirm)

**Files:**
- Modify: `backend/src/booking/service.py`
- Modify: `backend/src/booking/router.py`
- Create: `backend/tests/audit/test_booking_emit_sites.py`

**Interfaces consumed:** `audit.service.record_event`.

Same treatment: add `actor_user_id: int` keyword-only param to each service function, thread from router, emit inside the function BEFORE `db.commit()`.

Event types:
- `lock_seats` with `channel="consumer"` → `consumer_booked`
- `lock_seats` with `channel="walkin"` → `walkin_booked`
- `mint_billing_intent` → `billing_ref_generated`
- `provider_confirm` → `cash_confirmed`

`provider_id` for all of these is the trip's `provider_id` (look up via the trip in scope).

Summary format examples:
- `"Ahmed Hassan booked 2 seats on trip #47 (Cairo → Aswan, Oct 12)"` for consumer_booked
- `"Bob (provider) walk-in booked 3 seats on trip #47"` for walkin_booked
- `"Billing ref BOK-XXXX-XX generated for booking #12"` for billing_ref_generated
- `"Cash payment confirmed for booking #12 (SDG 1500)"` for cash_confirmed

- [ ] **Step 1: Write failing tests** — 4 tests, one per event type. Follow the pattern from Task 2's inventory tests (login as consumer / provider, POST the endpoint, assert audit row).

- [ ] **Step 2: Run tests to confirm they fail**

- [ ] **Step 3: Modify `booking/service.py`** — add `actor_user_id: int` keyword param to `lock_seats`, `mint_billing_intent`, `provider_confirm`; emit inside each just before the transaction commit.

- [ ] **Step 4: Update `booking/router.py`** — pass `actor_user_id=current_user.id` from each endpoint.

- [ ] **Step 5: Investigate Reaper booking-expiration coverage**

Grep for expire logic:
```bash
grep -rn "expire\|expired\|expires_at" backend/src/booking/ | head -20
```

If the expiration logic lives in `booking/service.py` (or another module the Reaper imports), add a `booking_expired` event there — actor_user_id can be the trip's provider (representing "the system did this to their trip"; alternatively use a sentinel like `None` and adjust the FK constraint — but that's more invasive, so prefer using the provider's id).

If the logic is inline in `booking/tasks.py` — that file is golden per CLAUDE.md. Skip the emit and add a note to CLAUDE.md's Known Limitations documenting the gap. Do NOT modify `tasks.py`.

Document the outcome (hooked / gap noted) in the commit message and in Task 11's docs update.

- [ ] **Step 6: Run booking emit tests + full suite**

Expected: 4 (or 5 if booking_expired hooked) new tests pass; suite green. Suite: 155 → 159 or 160.

- [ ] **Step 7: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/booking/ backend/tests/audit/test_booking_emit_sites.py
git commit -m "$(cat <<'EOF'
feat(audit): emit consumer_booked / walkin_booked / billing_ref / cash_confirmed

Threads actor_user_id through booking.service.lock_seats,
mint_billing_intent, and provider_confirm. lock_seats distinguishes
event_type by channel ('consumer' → consumer_booked, 'walkin' →
walkin_booked).

[If Reaper booking-expire hooked:] Also emits booking_expired from the
service-layer expire function the Reaper calls; if the logic was inline
in tasks.py it's flagged as a Known Limitation in CLAUDE.md instead.

4 new integration tests.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `GET /admin/providers/{provider_id}/log` endpoint

**Files:**
- Modify: `backend/src/admin/router.py`
- Create: `backend/tests/audit/test_query_log.py`

**Interfaces consumed:** `audit.service.query_log` from Task 1. `audit.schemas.AuditLogResponse` from Task 1.

**Interfaces produced (frontend consumes in Task 8):**
- `GET /admin/providers/{provider_id}/log?q=&event_type=&from=&to=&limit=100&before_id=`
- Returns `AuditLogResponse { items: AuditEventItem[], next_before_id: int | null }`
- 403 if non-admin; 404 if `provider_id` doesn't exist.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/audit/test_query_log.py` with 7 tests:
1. Happy path returns items newest-first.
2. Keyword filter (`q=Cairo`) narrows to matching summaries.
3. `event_type=trip_edited` filter.
4. Date range `from` / `to` filter.
5. Cursor pagination: request `limit=2` twice, get consecutive pages, `next_before_id` reaches `null`.
6. Non-admin (provider) hits endpoint → 403.
7. Unknown `provider_id` → 404.

Each test seeds a provider + a handful of `AuditEvent` rows directly via SQLAlchemy (no need to trigger real mutations — that's covered by Tasks 2-4).

- [ ] **Step 2: Run tests to confirm they fail**

Expected: all 7 fail with 404 (endpoint doesn't exist).

- [ ] **Step 3: Add the endpoint to `admin/router.py`**

Import at the top:
```python
from ..audit import service as audit_svc, schemas as audit_schemas
```

Add the endpoint (place it near the existing `/reports` endpoint at ~line 238):

```python
@router.get(
    "/providers/{provider_id}/log",
    response_model=audit_schemas.AuditLogResponse,
)
def provider_log(
    provider_id: int,
    q: Optional[str] = None,
    event_type: Optional[str] = None,
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = 100,
    before_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: auth_models.User = Depends(deps.require_admin),
):
    """Activity log for a single provider. Admin-only in Phase 1;
    Phase 2 will widen for operator-admin scoped to their acts_for_provider_id."""
    provider = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    rows, next_before = audit_svc.query_log(
        db,
        provider_id=provider_id,
        q=q, event_type=event_type,
        from_ts=from_, to_ts=to,
        limit=limit, before_id=before_id,
    )

    # Load actors in one query
    actor_ids = {r.actor_user_id for r in rows}
    actors = {
        u.id: u for u in db.query(auth_models.User).filter(auth_models.User.id.in_(actor_ids)).all()
    }

    items = []
    for r in rows:
        actor = actors.get(r.actor_user_id)
        actor_out = audit_schemas.AuditActor(
            id=r.actor_user_id,
            full_name=actor.full_name if actor else f"user #{r.actor_user_id}",
            role=actor.role if actor else "unknown",
        )
        items.append(audit_schemas.AuditEventItem(
            id=r.id, event_type=r.event_type, actor=actor_out,
            target_type=r.target_type, target_id=r.target_id,
            summary=r.summary, metadata=r.metadata_,
            created_at=r.created_at,
        ))

    return {"items": items, "next_before_id": next_before}
```

Grep `admin/router.py` for `require_admin` to confirm the dependency name; if different, use whatever the existing admin routes use.

- [ ] **Step 4: Run tests to confirm they pass**

Expected: 7 pass; suite 159 → 166.

- [ ] **Step 5: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/admin/router.py backend/tests/audit/test_query_log.py
git commit -m "$(cat <<'EOF'
feat(admin): GET /admin/providers/{id}/log endpoint

Admin-only endpoint that reads audit_events via audit.service.query_log
with query params for keyword ILIKE, event_type exact match, date range
(from/to), and cursor pagination (before_id). Actor names are joined in
one extra query so the response carries {id, full_name, role}.

Returns AuditLogResponse { items, next_before_id | null }.

7 new tests covering each filter, cursor boundary, admin auth, and
404-on-unknown-provider.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `GET /admin/providers/{provider_id}/reports` endpoint

**Files:**
- Modify: `backend/src/admin/router.py`
- Create: `backend/tests/audit/test_reports_drilldown.py`

**Interfaces produced:** `GET /admin/providers/{provider_id}/reports?from=&to=` — returns same shape as `GET /admin/reports?provider_id=X&from=&to=` reused verbatim from `finance/reports.py`.

- [ ] **Step 1: Write 2 failing tests** — happy-path (matches shape of existing `/admin/reports`) + auth (non-admin gets 403).

- [ ] **Step 2: Add the endpoint to `admin/router.py`**

```python
@router.get(
    "/providers/{provider_id}/reports",
    response_model=schemas.ReportsResponse,
)
def provider_reports(
    provider_id: int,
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: auth_models.User = Depends(deps.require_admin),
):
    """Per-provider drilldown. Thin wrapper that inlines provider_id from
    the URL path and reuses the existing reports aggregation."""
    provider = (
        db.query(auth_models.User)
        .filter(auth_models.User.id == provider_id, auth_models.User.role == "provider")
        .first()
    )
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    # Delegate to the same helper the existing /reports endpoint uses.
    return service.get_reports(db, from_=from_, to=to, provider_id=provider_id)
```

Grep `admin/service.py` and `admin/router.py` to find the actual helper name (the endpoint at line 238 calls it). Use whatever it's called; the point is to reuse, not reimplement.

- [ ] **Step 3: Run tests + full suite**

Expected: 2 pass; suite 166 → 168.

- [ ] **Step 4: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add backend/src/admin/router.py backend/tests/audit/test_reports_drilldown.py
git commit -m "$(cat <<'EOF'
feat(admin): GET /admin/providers/{id}/reports drilldown

Thin wrapper around the existing /admin/reports aggregation that infers
provider_id from the URL path. Same auth gate (admin-only) as the log
endpoint — becomes the natural place to widen for operator-admin scope
in Phase 2 without touching the shared aggregation code in finance/.

2 new tests.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend — Providers-tab rows become clickable + new detail-page skeleton with permissions panel

**Files:**
- Modify: `frontend/index-v2.html`

**Interfaces consumed:** existing `/admin/providers/{id}/approve|block|capabilities` endpoints (reused).

**Interfaces produced (Tasks 8 and 9 consume):**
- New screen id `screen-admin-provider-detail`, routable via `goto('admin-provider-detail')`.
- New STATE fields: `STATE.viewingProviderId: int | null` (init `null`), `STATE.viewingProvider: object | null` (cached provider row).
- New render function `renderProviderDetail()` mounts the page; individual panels get their own render helpers that Tasks 8 + 9 fill in.

- [ ] **Step 1: Add STATE fields**

Grep for the `STATE = {` initializer. Add:
```js
  viewingProviderId: null,
  viewingProvider: null,
```

- [ ] **Step 2: Rewrite `renderAdminProviders()` — gut inline controls, add click handler**

Current function at ~line 10170 renders rows with `capsBlock` + approve/block buttons inline. Replace with:

```js
async function renderAdminProviders() {
  const providers = await api('/admin/providers');
  $('#cnt-providers').textContent = providers.length;
  const list = $('#admin-provider-list');
  const empty = $('#admin-provider-empty');
  list.innerHTML = '';
  if (!providers.length) { empty.classList.remove('hidden'); list.classList.add('hidden'); return; }
  empty.classList.add('hidden'); list.classList.remove('hidden');
  providers.forEach(p => {
    const row = document.createElement('div');
    row.className = 'admin-row admin-row-clickable';
    row.style.cursor = 'pointer';
    row.innerHTML = `
      <div class="main">
        <div><span class="status-pill ${p.status}">${tStatus(p.status)}</span><span class="name">${escapeHtml(p.full_name)}</span></div>
        <div class="sub">${escapeHtml(p.email)} · ${escapeHtml(p.phone_number || '—')} · ${t('admin.row.joined')} ${fmtTime(p.created_at)} · <b>${p.trip_count}</b> ${t('admin.row.trips')}</div>
      </div>
      <div class="actions">
        <span class="chevron-right" aria-hidden="true">→</span>
      </div>
    `;
    row.addEventListener('click', () => {
      STATE.viewingProviderId = p.id;
      STATE.viewingProvider = p;
      goto('admin-provider-detail');
    });
    list.appendChild(row);
  });
}
```

The old helpers `adminProviderAction` and `setProviderCapability` at ~lines 10211-10231 stay in the file — Task 7 Step 4's detail-page panel calls them.

- [ ] **Step 3: Add the new `<section>` markup for the detail page**

Insert AFTER the existing `<section class="screen" id="screen-admin-home">` block (grep for it around line 6309). The new section:

```html
    <!-- Admin: single-provider detail page -->
    <section class="screen" id="screen-admin-provider-detail">
      <div class="admin-detail-wrap">
        <div class="admin-detail-header">
          <button class="ghost-back" id="admin-detail-back">← <span data-i18n="admin.provider.detail.back">Back to providers</span></button>
          <div id="admin-detail-heading"><!-- populated by renderProviderDetail --></div>
        </div>

        <!-- Panel: permissions -->
        <section class="p-pillow admin-detail-panel" id="admin-detail-permissions">
          <h3 data-i18n="admin.provider.detail.permissions">Access &amp; permissions</h3>
          <div id="admin-detail-permissions-body"><!-- populated --></div>
        </section>

        <!-- Panel: activity log (filled in by Task 8) -->
        <section class="p-pillow admin-detail-panel" id="admin-detail-log">
          <h3 data-i18n="admin.provider.detail.log">Activity log</h3>
          <div id="admin-detail-log-body"><!-- populated by Task 8 --></div>
        </section>

        <!-- Panel: reports (filled in by Task 9) -->
        <section class="p-pillow admin-detail-panel" id="admin-detail-reports">
          <h3 data-i18n="admin.provider.detail.reports">Reports</h3>
          <div id="admin-detail-reports-body"><!-- populated by Task 9 --></div>
        </section>
      </div>
    </section>
```

- [ ] **Step 4: Register the screen everywhere**

Grep for the CSS `body[data-screen="admin-home"]` visibility chain near line 816. Immediately after that line, add:
```css
  body[data-screen="admin-provider-detail"] #screen-admin-provider-detail,
```

Grep for `PILLOW_SCREENS`. Add `'admin-provider-detail'` to the Set literal.

- [ ] **Step 5: Add `renderProviderDetail()` + permissions render helper**

Grep for `renderAdminProviders`. Add these functions immediately after `setProviderCapability`:

```js
async function renderProviderDetail() {
  const pid = STATE.viewingProviderId;
  if (!pid) { goto('admin-home'); return; }

  // Re-fetch so status/capability changes elsewhere are reflected on entry.
  try {
    const providers = await api('/admin/providers');
    const p = providers.find(x => x.id === pid);
    if (!p) { toast(t('admin.provider.detail.not_found'), true); goto('admin-home'); return; }
    STATE.viewingProvider = p;
  } catch (e) { toast(e.message, true); return; }

  renderProviderDetailHeader();
  renderProviderDetailPermissions();
  // Task 8:
  if (typeof renderProviderAuditLog === 'function') renderProviderAuditLog(true /*reset*/);
  // Task 9:
  if (typeof renderProviderReports === 'function') renderProviderReports();
}

function renderProviderDetailHeader() {
  const p = STATE.viewingProvider;
  $('#admin-detail-heading').innerHTML = `
    <div class="ad-name-row">
      <span class="status-pill ${p.status}">${tStatus(p.status)}</span>
      <span class="ad-name">${escapeHtml(p.full_name)}</span>
    </div>
    <div class="ad-sub">${escapeHtml(p.email)} · ${escapeHtml(p.phone_number || '—')}</div>
  `;
}

function renderProviderDetailPermissions() {
  const p = STATE.viewingProvider;
  const body = $('#admin-detail-permissions-body');
  const capsBlock = p.status === 'active' ? `
    <div class="caps">
      <span class="cap-label">${t('admin.caps.label')}</span>
      <label class="cap"><input type="checkbox" data-cap="can_add_trips"    ${p.can_add_trips    ? 'checked' : ''}> ${t('admin.caps.add')}</label>
      <label class="cap"><input type="checkbox" data-cap="can_edit_trips"   ${p.can_edit_trips   ? 'checked' : ''}> ${t('admin.caps.edit')}</label>
      <label class="cap"><input type="checkbox" data-cap="can_delete_trips" ${p.can_delete_trips ? 'checked' : ''}> ${t('admin.caps.delete')}</label>
    </div>` : '';
  body.innerHTML = `
    ${capsBlock}
    <div class="ad-actions">
      ${ p.status === 'active'
          ? `<button class="btn-inline danger" data-action="block">${t('admin.action.block')}</button>`
          : `<button class="btn-inline success" data-action="approve">${t('admin.action.approve')}</button>` }
    </div>
  `;
  body.querySelector('[data-action="approve"]')?.addEventListener('click', async () => {
    await adminProviderAction(p.id, 'approve');
    renderProviderDetail();  // refetch + re-render
  });
  body.querySelector('[data-action="block"]')?.addEventListener('click', async () => {
    await adminProviderAction(p.id, 'block');
    renderProviderDetail();
  });
  body.querySelectorAll('.caps input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => setProviderCapability(p.id, cb.dataset.cap, cb.checked, cb));
  });
}
```

- [ ] **Step 6: Wire the back button + route entry**

Grep for the `goto()` router/switch (there's a per-screen entry hook pattern from the recent reset-password work). Add:
```js
if (screen === 'admin-provider-detail') { renderProviderDetail(); }
```

And wire the back button:
```js
$('#admin-detail-back').addEventListener('click', () => goto('admin-home'));
```

(Or use `back()` if the app has a history-pop helper — grep for it.)

- [ ] **Step 7: Add i18n keys**

Add to BOTH `en:` and `ar:` blocks:

English:
```js
    "admin.provider.detail.back": "Back to providers",
    "admin.provider.detail.title": "Provider detail",
    "admin.provider.detail.permissions": "Access & permissions",
    "admin.provider.detail.log": "Activity log",
    "admin.provider.detail.reports": "Reports",
    "admin.provider.detail.not_found": "Provider not found",
```

Arabic:
```js
    "admin.provider.detail.back": "العودة إلى المشغلين",
    "admin.provider.detail.title": "تفاصيل المشغل",
    "admin.provider.detail.permissions": "الوصول والصلاحيات",
    "admin.provider.detail.log": "سجل النشاط",
    "admin.provider.detail.reports": "التقارير",
    "admin.provider.detail.not_found": "المشغل غير موجود",
```

- [ ] **Step 8: Manual smoke test**

Start the backend and open v2:
```bash
cd backend && ./venv/bin/uvicorn src.main:app --reload
```
Open `http://localhost:8000/app/`. Sign in as admin. Providers tab → row is clickable → detail page renders with the provider's name/email/status and the permissions panel with capability toggles + block/approve button. Toggling a capability updates via the existing endpoint (verify with a page refresh). Back button returns to Providers tab. Log + Reports panels are empty (Task 8/9 fill them).

- [ ] **Step 9: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add frontend/index-v2.html
git commit -m "$(cat <<'EOF'
feat(v2): admin provider-detail page skeleton + permissions panel

Providers-tab rows lose their inline capability toggles + approve/block
buttons — the row is now a whole-row clickable that routes to a new
screen-admin-provider-detail page. Detail page has three panels laid out
top-to-bottom: header, permissions (capability toggles + block/approve
reused from the removed inline controls), and empty log + reports panels
that Tasks 8 + 9 fill in.

Screen registered in PILLOW_SCREENS + CSS body-selector chain so the
pillow styling kicks in. Detail page refetches /admin/providers on
entry so mutations elsewhere are reflected.

6 new EN+AR i18n keys.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Frontend — Activity log panel

**Files:**
- Modify: `frontend/index-v2.html`

**Interfaces consumed:** `GET /admin/providers/{id}/log` from Task 5. `STATE.viewingProviderId` from Task 7.

- [ ] **Step 1: Add STATE for pagination + filters**

```js
  auditLog: { items: [], nextBefore: null, filters: { q: '', event_type: '', from: '', to: '' } },
```

- [ ] **Step 2: Populate `#admin-detail-log-body` with filter strip + rows + Load more**

Add `renderProviderAuditLog(reset = false)`:

```js
async function renderProviderAuditLog(reset = false) {
  const pid = STATE.viewingProviderId;
  if (!pid) return;
  const body = $('#admin-detail-log-body');
  if (reset) {
    STATE.auditLog = { items: [], nextBefore: null, filters: STATE.auditLog?.filters || { q: '', event_type: '', from: '', to: '' } };
    body.innerHTML = `
      <div class="filter-strip audit-filter-strip">
        <div class="fld"><label>${t('admin.provider.log.filter.keyword')}</label><input type="text" id="al-q" value="${STATE.auditLog.filters.q}" placeholder="${t('admin.provider.log.filter.keyword_ph')}"></div>
        <div class="fld"><label>${t('admin.provider.log.filter.event_type')}</label>
          <select id="al-event-type">
            <option value="">${t('admin.provider.log.filter.event_type_all')}</option>
            ${AUDIT_EVENT_TYPES.map(et => `<option value="${et}" ${STATE.auditLog.filters.event_type === et ? 'selected' : ''}>${t('admin.provider.log.event.' + et)}</option>`).join('')}
          </select>
        </div>
        <div class="fld"><label>${t('admin.provider.log.filter.date_from')}</label><input type="date" id="al-from" value="${STATE.auditLog.filters.from}"></div>
        <div class="fld"><label>${t('admin.provider.log.filter.date_to')}</label><input type="date" id="al-to" value="${STATE.auditLog.filters.to}"></div>
        <button class="btn-inline" id="al-apply">${t('admin.provider.log.filter.apply')}</button>
      </div>
      <div id="al-rows" class="audit-log-rows"></div>
      <div id="al-empty" class="audit-empty hidden">${t('admin.provider.log.empty')}</div>
      <div id="al-loadmore-wrap" class="hidden" style="text-align:center; margin-top:12px;">
        <button class="btn-inline" id="al-loadmore">${t('admin.provider.log.load_more')}</button>
      </div>
    `;
    // 280ms debounced keyword input
    let kwTimer = null;
    $('#al-q').addEventListener('input', () => {
      clearTimeout(kwTimer);
      kwTimer = setTimeout(() => { STATE.auditLog.filters.q = $('#al-q').value; renderProviderAuditLog(true); }, 280);
    });
    $('#al-event-type').addEventListener('change', () => { STATE.auditLog.filters.event_type = $('#al-event-type').value; renderProviderAuditLog(true); });
    $('#al-from').addEventListener('change', () => { STATE.auditLog.filters.from = $('#al-from').value; renderProviderAuditLog(true); });
    $('#al-to').addEventListener('change', () => { STATE.auditLog.filters.to = $('#al-to').value; renderProviderAuditLog(true); });
    $('#al-apply').addEventListener('click', () => renderProviderAuditLog(true));
    $('#al-loadmore').addEventListener('click', () => loadMoreAuditLog());
  }
  await fetchAndAppendAuditLog(reset);
}

async function fetchAndAppendAuditLog(reset) {
  const pid = STATE.viewingProviderId;
  const f = STATE.auditLog.filters;
  const params = new URLSearchParams();
  if (f.q) params.set('q', f.q);
  if (f.event_type) params.set('event_type', f.event_type);
  if (f.from) params.set('from', f.from);
  if (f.to) params.set('to', f.to);
  if (!reset && STATE.auditLog.nextBefore) params.set('before_id', STATE.auditLog.nextBefore);
  params.set('limit', '100');
  try {
    const data = await api(`/admin/providers/${pid}/log?${params}`);
    if (reset) STATE.auditLog.items = [];
    STATE.auditLog.items.push(...data.items);
    STATE.auditLog.nextBefore = data.next_before_id;
    renderAuditLogRows();
  } catch (e) { toast(e.message, true); }
}

function loadMoreAuditLog() { fetchAndAppendAuditLog(false); }

function renderAuditLogRows() {
  const rows = $('#al-rows');
  const empty = $('#al-empty');
  const loadMoreWrap = $('#al-loadmore-wrap');
  if (!STATE.auditLog.items.length) {
    rows.innerHTML = '';
    empty.classList.remove('hidden');
    loadMoreWrap.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  rows.innerHTML = STATE.auditLog.items.map(item => `
    <div class="audit-row event-${item.event_type}">
      <div class="ae-icon">${AUDIT_ICONS[item.event_type] || '•'}</div>
      <div class="ae-body">
        <div class="ae-summary">${escapeHtml(item.summary)}</div>
        <div class="ae-meta">
          <span class="ae-actor">${escapeHtml(item.actor.full_name)} <span class="role-tag">${escapeHtml(item.actor.role)}</span></span>
          <span class="ae-time">${fmtRelativeTime(item.created_at)}</span>
        </div>
      </div>
    </div>
  `).join('');
  loadMoreWrap.classList.toggle('hidden', !STATE.auditLog.nextBefore);
}

const AUDIT_EVENT_TYPES = [
  'trip_created', 'trip_edited', 'trip_deleted',
  'walkin_booked', 'consumer_booked', 'billing_ref_generated', 'cash_confirmed',
  'payment_confirmed',
  'provider_approved', 'provider_blocked', 'provider_unblocked',
  'capability_changed',
];
const AUDIT_ICONS = {
  trip_created: '＋', trip_edited: '✎', trip_deleted: '✕',
  walkin_booked: '🚶', consumer_booked: '🎫', billing_ref_generated: '§',
  cash_confirmed: '$', payment_confirmed: '✓',
  provider_approved: '✓', provider_blocked: '⛔', provider_unblocked: '↺',
  capability_changed: '⚙',
};
```

If `fmtRelativeTime` doesn't exist in the file, grep for a similar helper (`fmtTime` exists; may be enough). If not, add a simple relative-time helper.

- [ ] **Step 3: Add i18n keys**

Add to BOTH `en:` and `ar:` blocks (~24 keys per language):

**English:**
```js
    "admin.provider.log.filter.keyword": "Keyword",
    "admin.provider.log.filter.keyword_ph": "Search summary…",
    "admin.provider.log.filter.event_type": "Event",
    "admin.provider.log.filter.event_type_all": "All events",
    "admin.provider.log.filter.date_from": "From",
    "admin.provider.log.filter.date_to": "To",
    "admin.provider.log.filter.apply": "Apply",
    "admin.provider.log.empty": "No activity yet. Log tracking started 2026-07-23; earlier actions aren't recorded.",
    "admin.provider.log.load_more": "Load more",
    "admin.provider.log.event.trip_created": "Trip created",
    "admin.provider.log.event.trip_edited": "Trip edited",
    "admin.provider.log.event.trip_deleted": "Trip deleted",
    "admin.provider.log.event.walkin_booked": "Walk-in booked",
    "admin.provider.log.event.consumer_booked": "Consumer booked",
    "admin.provider.log.event.billing_ref_generated": "Billing ref generated",
    "admin.provider.log.event.cash_confirmed": "Cash confirmed",
    "admin.provider.log.event.payment_confirmed": "Payment confirmed",
    "admin.provider.log.event.provider_approved": "Provider approved",
    "admin.provider.log.event.provider_blocked": "Provider blocked",
    "admin.provider.log.event.provider_unblocked": "Provider unblocked",
    "admin.provider.log.event.capability_changed": "Capability changed",
```

**Arabic:**
```js
    "admin.provider.log.filter.keyword": "كلمة مفتاحية",
    "admin.provider.log.filter.keyword_ph": "بحث في الملخص…",
    "admin.provider.log.filter.event_type": "الحدث",
    "admin.provider.log.filter.event_type_all": "كل الأحداث",
    "admin.provider.log.filter.date_from": "من",
    "admin.provider.log.filter.date_to": "إلى",
    "admin.provider.log.filter.apply": "تطبيق",
    "admin.provider.log.empty": "لا يوجد نشاط بعد. بدأ تتبّع السجل في 2026-07-23؛ الإجراءات السابقة غير مسجّلة.",
    "admin.provider.log.load_more": "تحميل المزيد",
    "admin.provider.log.event.trip_created": "تم إنشاء رحلة",
    "admin.provider.log.event.trip_edited": "تم تعديل رحلة",
    "admin.provider.log.event.trip_deleted": "تم حذف رحلة",
    "admin.provider.log.event.walkin_booked": "حجز مباشر",
    "admin.provider.log.event.consumer_booked": "حجز عميل",
    "admin.provider.log.event.billing_ref_generated": "تم إصدار رقم فاتورة",
    "admin.provider.log.event.cash_confirmed": "تأكيد نقدي",
    "admin.provider.log.event.payment_confirmed": "تأكيد الدفع",
    "admin.provider.log.event.provider_approved": "تم اعتماد المشغل",
    "admin.provider.log.event.provider_blocked": "تم حظر المشغل",
    "admin.provider.log.event.provider_unblocked": "تم رفع الحظر",
    "admin.provider.log.event.capability_changed": "تغيير الصلاحيات",
```

The "log tracking started 2026-07-23" date in the empty-state string is pinned to today; do not change it during implementation.

- [ ] **Step 4: Manual smoke test**

Trigger a few provider actions (edit a trip, toggle a capability), then visit the detail page. Log rows appear. Try keyword filter. Try event-type filter. Try Load more (if you have > 100 rows — otherwise verify the wrap stays hidden).

- [ ] **Step 5: Commit**

---

## Task 9: Frontend — Reports panel + Reports tab drilldown link

**Files:**
- Modify: `frontend/index-v2.html`

**Interfaces consumed:** `GET /admin/providers/{id}/reports` from Task 6. Reuses existing reports table rendering.

- [ ] **Step 1: Populate `#admin-detail-reports-body` with the existing report tables scoped to this provider**

Grep for `renderAdminReports` — that's where the existing Reports tab renders the aggregate view. Extract the table-rendering portion into a helper that accepts a report payload:

```js
function renderReportTables(data, target) {
  // (extracted from renderAdminReports — renders Operational + Financial tables)
  target.innerHTML = `
    <div class="report-section"><h4>${t('admin.reports.operational')}</h4>${buildOperationalTable(data)}</div>
    <div class="report-section"><h4>${t('admin.reports.financial')}</h4>${buildFinancialTable(data)}</div>
    <button class="btn-inline" id="ap-export-csv">${t('admin.reports.export_csv')}</button>
  `;
}
```

Then:
```js
async function renderProviderReports() {
  const pid = STATE.viewingProviderId;
  const body = $('#admin-detail-reports-body');
  try {
    const data = await api(`/admin/providers/${pid}/reports`);
    renderReportTables(data, body);
    $('#ap-export-csv')?.addEventListener('click', () => exportReportsCsv(data, `provider-${pid}`));
  } catch (e) { toast(e.message, true); }
}
```

`buildOperationalTable`, `buildFinancialTable`, `exportReportsCsv` may already exist inside `renderAdminReports` — if so, extract them as top-level helpers so both Reports tab and detail page use them.

- [ ] **Step 2: Add "View →" link on Reports tab per-provider breakdown rows**

Grep for `renderAdminReports` again — find where per-provider rows are rendered. Add a trailing cell / link:
```html
<a href="#" class="report-drill" data-provider-id="${row.provider_id}">${t('admin.reports.drilldown_link')} →</a>
```

Wire the click:
```js
document.querySelectorAll('.report-drill').forEach(el => {
  el.addEventListener('click', (e) => {
    e.preventDefault();
    STATE.viewingProviderId = parseInt(el.dataset.providerId, 10);
    STATE.viewingProvider = null;  // force refetch in renderProviderDetail
    goto('admin-provider-detail');
    // TODO: scroll to #admin-detail-reports on entry
  });
});
```

- [ ] **Step 3: Add i18n keys** (2 new: `admin.reports.drilldown_link`, `admin.reports.operational`, `admin.reports.financial`, `admin.reports.export_csv` — reuse existing if present).

- [ ] **Step 4: Manual smoke test**

Reports tab → per-provider row's "View →" → detail page opens → Reports panel populated with same numbers.

- [ ] **Step 5: Commit**

---

## Task 10: Docs

**Files:**
- Modify: `claude.md`

- [ ] **Step 1: Update the "Deliberately deferred (V2)" section**

Find the line `- Audit log (A-MON-04).` Replace with:
```
- Audit log (A-MON-04). **Partially shipped 2026-07-23** — see Recent Fixes. Phase 1 covers admin visibility into per-provider actions; Phase 2 will widen access to a new operator-admin sub-role.
```

- [ ] **Step 2: Add a Recent Fixes entry at the top**

Immediately after `## 🐛 Recent fixes (most recent first)`, add:

```markdown
- **Provider detail page + audit log Phase 1 (2026-07-23)**: new `audit_events` table + `record_event()` service wired into every mutation site in `inventory/service.py`, `booking/service.py`, and `admin/service.py`. Emit uses a nested SAVEPOINT (`db.begin_nested()`) so a failed audit insert can never break the underlying mutation, and every call is wrapped in a swallowing try/except with `[AUDIT]` log fallback. New `GET /admin/providers/{id}/log` endpoint with keyword ILIKE + event_type + date range + cursor pagination; new `GET /admin/providers/{id}/reports` drilldown reusing `finance/reports.py`. Admin Providers tab rows became clickable — inline capability toggles + block/approve buttons moved to new `screen-admin-provider-detail` page (Header + Permissions + Activity Log + Reports panels). ~28 new backend tests (140 → 168). Spec: `docs/superpowers/specs/2026-07-23-provider-detail-and-audit-log-design.md`, plan: `docs/superpowers/plans/2026-07-23-provider-detail-and-audit-log-phase-1.md`. Phase 2 (operator-admin sub-role — new role acts_for_provider_id, admin creation UI, scoped experience) gets its own spec+plan cycle after this ships.
```

- [ ] **Step 3: If Task 4's Reaper investigation surfaced a `booking_expired` gap**

Add to the Known Limitations table:
```
| Reaper booking-expiration events not logged | Reaper (`backend/src/booking/tasks.py`) is CLAUDE.md-protected — expiration logic sits inline in it, so the audit log doesn't record when locks are released. | Refactor the expire logic into a service-layer function the Reaper calls, then hook `record_event()` there in a follow-up. |
```

(Skip this step if Task 4 successfully hooked `booking_expired` via a service function.)

- [ ] **Step 4: Verify no stale references**

```bash
grep -n "audit log" claude.md | head
```
Expected: only the updated deferred entry, the new Recent Fixes entry, and any incidental mentions.

- [ ] **Step 5: Commit**

```bash
cd /Users/muthana/Documents/Projects/tazkirati/ticket_booking_platform
git add claude.md
git commit -m "$(cat <<'EOF'
docs(claude.md): Phase 1 audit log + provider detail page shipped

Updates Deferred section (audit log now partially shipped) and adds
Recent Fixes entry describing the full Phase 1 landing.

[If applicable:] Notes the Reaper booking-expiration gap under Known
Limitations — expire logic lives inline in tasks.py which is
CLAUDE.md-protected, so booking_expired events aren't logged. Deferred
to a follow-up that first extracts the expire logic into a service.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Full backend suite**

```bash
cd backend && ./venv/bin/pytest -q
```
Expected: ~168 tests pass (140 before + ~28 new). Adjust if `booking_expired` was hooked (+1 test) or if any pre-existing test needed adjustment for the new `actor_user_id` service kwargs.

- [ ] **Grep confirms audit hooks landed everywhere**

```bash
grep -rn "audit_svc.record_event" backend/src/ | head -20
```
Expected: ~11-12 calls across inventory/service.py, admin/service.py, booking/service.py.

- [ ] **Grep confirms v1 is untouched**

```bash
git diff main -- frontend/index.html
```
Expected: no diff.

- [ ] **Grep confirms Reaper untouched**

```bash
git diff main -- backend/src/booking/tasks.py
```
Expected: no diff.

- [ ] **Final commit-level review**

```bash
git log --oneline d7789ac..HEAD
```
Expected: 10 commits landed (one per task). Each independently reviewable and rollback-safe.
