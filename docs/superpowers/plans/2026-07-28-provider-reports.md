# Provider Reports (Self-Service, Gated) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `can_view_reports` per-provider capability that unlocks a self-service Reports tab in the provider's tab bar. The tab shows the same financial + operational data the admin sees for that provider, but reworded in the operator's voice ("Revenue" / "Commission Deducted" / "My Net" instead of "Financial" / "Commissions Earned" / "Net Payout").

**Architecture:** Extend the existing `users.can_*` capability pattern with one more Boolean (default FALSE). Move the two period-helper functions out of `admin/router.py` into `finance/reports.py` so both admin and provider routes share them. New `backend/src/reports/` package exposes `GET /reports/mine` — a thin wrapper over the existing `finance.reports.build_reports` orchestrator, scoped to the caller's own `provider_id`, with `by_provider` arrays trimmed from the response. Frontend adds a fourth capability chip on the admin Provider Detail page and a new Reports tab / panel / fetch handler / CSV export inside `#screen-provider-home` — pillow-styled, gated on the new flag.

**Tech Stack:** FastAPI + Pydantic v2 · SQLAlchemy ORM (Neon Postgres + SQLite in tests) · pytest + FastAPI TestClient · Vanilla JS + pillow CSS (v2) inside `frontend/index.html`.

**Spec:** `docs/superpowers/specs/2026-07-28-provider-reports-design.md`

## Global Constraints

- New column `users.can_view_reports Boolean NOT NULL DEFAULT FALSE`. Python-side default matches (Column(Boolean, default=False, nullable=False)).
- Idempotent migration: `ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_reports BOOLEAN NOT NULL DEFAULT FALSE` — placed alongside the existing three cap migrations in `backend/src/main.py :: _migrate_if_needed()` (currently at lines 50-52).
- `GET /reports/mine` uses `Depends(require_active_provider)` for auth + role AND an explicit `provider.can_view_reports` gate that 403s with the exact detail string: `"Reports are not enabled for your account. Contact an administrator."`
- Response body of `/reports/mine` MUST be the admin `/admin/reports` body shape minus the two `by_provider` arrays — headline totals (`total_commission`, `total_bookings`, `total_passengers`) preserved. Trim with `payload["financial"].pop("by_provider", None)` etc.
- Endpoint does NOT accept a `provider_id` query param — `provider_id` is hardcoded from the JWT `provider.id`, so cross-provider read is impossible even with a crafted request.
- The provider-side i18n copy is the deliberate contrast with admin copy: `provider.reports.col.commission` = "Commission Deducted" (NOT "Commissions Earned"), `provider.reports.col.net` = "My Net" (NOT "Net Payout"), section title `provider.reports.revenue.title` = "Revenue" (NOT "Financial"). Admin's own copy stays unchanged.
- Every new user-visible string gets both EN and AR entries. Numeric table cells force `dir="ltr"` under RTL, matching the admin Reports pattern.
- Provider Reports tab is hidden entirely when the cap is off — no ghost tab, no locked-lock icon, no "your admin has not enabled reports" message.
- Follow pillow (v2) primitives only — `.pillow`, `.report-table`, `.reports-section`, `.reports-filter` are already defined for the admin Reports tab. Reuse them.
- No `--no-verify`, no `--amend`. One commit per task.

---

## File Structure

**Backend files touched:**
- Modify: `backend/src/auth/models.py` — add one Column.
- Modify: `backend/src/main.py` — one line in `_migrate_if_needed`.
- Modify: `backend/src/admin/schemas.py` — add one Optional field to `ProviderCapabilitiesUpdate`.
- Modify: `backend/src/admin/service.py` — extend `update_provider_capabilities` signature.
- Modify: `backend/src/admin/router.py` — pass the new field through in the capabilities handler; delete the two period helpers (moved to finance/reports.py).
- Modify: `backend/src/finance/reports.py` — add `validate_period` + `default_period` (moved from admin/router.py, renamed without underscore).
- Create: `backend/src/reports/__init__.py` (empty).
- Create: `backend/src/reports/router.py` — one endpoint.
- Modify: `backend/src/main.py` — one `app.include_router(reports_router)` line.
- Modify: `backend/tests/finance/test_provider_capabilities.py` — add 2 tests.
- Create: `backend/tests/reports/__init__.py` (empty).
- Create: `backend/tests/reports/test_my_reports.py` — 7 tests.

**Frontend files touched:**
- Modify: `frontend/index.html` — new markup (admin cap chip + provider Reports tab + provider Reports panel), CSS delta if any, EN + AR i18n keys, JS refresh/render handlers, event wiring.

Three tasks — plumbing → endpoint → UI. Each has an independent reviewer gate.

---

## Task 1: Backend — capability flag + toggle plumbing

**Files:**
- Modify: `backend/src/auth/models.py` (add column near lines 29-31)
- Modify: `backend/src/main.py:_migrate_if_needed` (add ALTER line near line 52)
- Modify: `backend/src/admin/schemas.py` (extend `ProviderCapabilitiesUpdate`)
- Modify: `backend/src/admin/service.py` (extend `update_provider_capabilities` signature)
- Modify: `backend/src/admin/router.py:85-101` (pass the new field through)
- Modify: `backend/tests/finance/test_provider_capabilities.py` (add 2 tests)

**Interfaces:**
- Consumes: existing `ProviderCapabilitiesUpdate` schema, existing `update_provider_capabilities` service, existing `PATCH /admin/providers/{id}/capabilities` route, existing `provider_capability_changed` notification.
- Produces:
  - `User.can_view_reports: bool` — new SQLAlchemy Column, default False, nullable False. Serialized wherever the other three caps already are (via `_decorate_provider` and the User schema — no schema edit needed if the response uses the ORM's `__dict__` via `from_attributes`).
  - `ProviderCapabilitiesUpdate.can_view_reports: Optional[bool] = None` — one new field on the existing partial-update schema.
  - `service.update_provider_capabilities(..., can_view_reports: Optional[bool] = None, ...)` — one new keyword arg. When not None, sets `provider.can_view_reports` and includes `"can_view_reports"` in the change payload the existing `provider_capability_changed` notification emits.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/finance/test_provider_capabilities.py`:

```python
def test_default_can_view_reports_is_false(provider):
    """Reports visibility deliberately defaults OFF — one exception to the
    'other three caps default TRUE' pattern (see spec §1). New providers get
    no Reports tab until an admin flips the switch."""
    assert provider.can_view_reports is False


def test_patch_can_view_reports(client, auth_header, provider):
    """Admin can flip can_view_reports via the same capabilities endpoint."""
    r = client.patch(
        f"/admin/providers/{provider.id}/capabilities",
        headers=auth_header,
        json={"can_view_reports": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_view_reports"] is True
    # Other three caps still on their defaults.
    assert body["can_add_trips"] is True
    assert body["can_edit_trips"] is True
    assert body["can_delete_trips"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/finance/test_provider_capabilities.py::test_default_can_view_reports_is_false tests/finance/test_provider_capabilities.py::test_patch_can_view_reports -v
```

Expected: both FAIL with `AttributeError: 'User' object has no attribute 'can_view_reports'` (or similar KeyError on the JSON body).

- [ ] **Step 3: Add the column on the User model**

In `backend/src/auth/models.py`, after the existing three cap columns (lines 29-31), add:

```python
    can_view_reports = Column(Boolean, default=False, nullable=False)
```

- [ ] **Step 4: Add the migration line**

In `backend/src/main.py :: _migrate_if_needed()`, after the three existing cap migrations (currently lines 50-52), add:

```python
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_reports BOOLEAN NOT NULL DEFAULT FALSE",
```

- [ ] **Step 5: Extend the schema**

In `backend/src/admin/schemas.py`, find `class ProviderCapabilitiesUpdate` and add one field. Follow the existing field style (all `Optional[bool] = None`):

```python
    can_view_reports: Optional[bool] = None
```

- [ ] **Step 6: Extend the service signature**

In `backend/src/admin/service.py :: update_provider_capabilities`, add the new keyword arg. Style match: after the existing `can_delete_trips` branch, insert an equivalent block for `can_view_reports`. Include the field name in whatever change-payload dict feeds the `provider_capability_changed` notification (grep for `changed_fields` or the notification payload construction inside that function).

Signature becomes:

```python
def update_provider_capabilities(
    db,
    *,
    provider_id: int,
    can_add_trips: Optional[bool] = None,
    can_edit_trips: Optional[bool] = None,
    can_delete_trips: Optional[bool] = None,
    can_view_reports: Optional[bool] = None,
    actor_user_id: int,
):
```

Branch pattern (place adjacent to the existing three, matching whatever style is already there):

```python
if can_view_reports is not None:
    user.can_view_reports = can_view_reports
    # + whatever the existing branches do to track the change in the notification payload
```

**Important:** read the existing three branches first to confirm the exact side-effect pattern (some pattern like `if user.can_add_trips != can_add_trips: user.can_add_trips = ...; changes["can_add_trips"] = ...`). Match it verbatim, don't invent new plumbing.

- [ ] **Step 7: Pass the new field through in the router**

In `backend/src/admin/router.py:93-100`, add the fourth kwarg to the `service.update_provider_capabilities(...)` call:

```python
    user = service.update_provider_capabilities(
        db,
        provider_id=provider_id,
        can_add_trips=payload.can_add_trips,
        can_edit_trips=payload.can_edit_trips,
        can_delete_trips=payload.can_delete_trips,
        can_view_reports=payload.can_view_reports,
        actor_user_id=admin.id,
    )
```

Also update the docstring at line 91 from `{can_add_trips, can_edit_trips, can_delete_trips}` to `{can_add_trips, can_edit_trips, can_delete_trips, can_view_reports}`.

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/finance/test_provider_capabilities.py -v
```

Expected: all tests pass (existing + 2 new).

- [ ] **Step 9: Run the full backend suite**

```bash
cd backend && python -m pytest -q
```

Expected: All previously-passing tests still pass. Baseline was 182 after the Personal Information ship; expect 184.

- [ ] **Step 10: Commit**

```bash
git add backend/src/auth/models.py backend/src/main.py backend/src/admin/schemas.py backend/src/admin/service.py backend/src/admin/router.py backend/tests/finance/test_provider_capabilities.py
git commit -m "$(cat <<'EOF'
feat(admin): add can_view_reports capability toggle

New Boolean column on the users table (default FALSE — one deliberate
deviation from the other three caps' default TRUE, since financial
visibility is more sensitive than trip management). Extended
ProviderCapabilitiesUpdate schema, update_provider_capabilities
service, and PATCH /admin/providers/{id}/capabilities router handler
accept the new field. Existing provider_capability_changed
notification fans it out to the affected provider on toggle.

Idempotent migration adds the column to existing deployments.

Foundation for the upcoming provider-side Reports tab.
EOF
)"
```

---

## Task 2: Backend — /reports/mine endpoint + period helper refactor

**Files:**
- Modify: `backend/src/admin/router.py` — delete `_validate_period` + `_default_period` (lines ~23-42), delete `_YYYY_MM` and `_dt` imports if now unused; update both callers (lines ~268-270 and ~298-300) to import from `finance.reports`.
- Modify: `backend/src/finance/reports.py` — add `validate_period` + `default_period` (moved from admin/router.py). Keep the exact behavior (same YYYY-MM regex, 24-month cap, 6-month default window).
- Create: `backend/src/reports/__init__.py` (empty).
- Create: `backend/src/reports/router.py` (~30 lines, see Step 4).
- Modify: `backend/src/main.py` — one `app.include_router(reports_router)` line.
- Create: `backend/tests/reports/__init__.py` (empty).
- Create: `backend/tests/reports/test_my_reports.py` — 7 tests.

**Interfaces:**
- Consumes: `finance.reports.build_reports` (existing orchestrator returning `dict` with keys `period`, `financial`, `operational`), `finance.reports.default_period` + `validate_period` (moved this task), `auth.dependencies.require_active_provider`, `User.can_view_reports` (Task 1).
- Produces:
  - `finance.reports.validate_period(from_str, to_str)` — same behavior as the old `_validate_period` in `admin/router.py`. Raises HTTPException(400).
  - `finance.reports.default_period() -> tuple[str, str]` — same behavior as the old `_default_period`. Returns YYYY-MM strings.
  - `GET /reports/mine?from=YYYY-MM&to=YYYY-MM` — auth: provider role + cap check. Response body: `{period, financial: {total_commission, by_month}, operational: {total_bookings, total_passengers, by_month}}`. 403 with the exact string `"Reports are not enabled for your account. Contact an administrator."` when cap is off.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/reports/__init__.py` (empty) and `backend/tests/reports/test_my_reports.py`:

```python
"""GET /reports/mine — provider-scoped self-service reports.

Seven scenarios: cap-off 403, cap-on happy path, cross-provider scope,
default period, explicit period, unauth 401, and customer-role 403.
"""
import pytest

from src.auth.models import User
from src.auth.utils import hash_password


@pytest.fixture
def provider_with_reports(db):
    """A provider WITH the reports capability enabled."""
    u = User(
        email="p-reports@x.com", full_name="Provider With Reports",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
        can_view_reports=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def provider_without_reports(db):
    """A provider WITHOUT the reports capability (the default state)."""
    u = User(
        email="p-noreports@x.com", full_name="Provider No Reports",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
        # can_view_reports defaults to False
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


@pytest.fixture
def customer(db):
    u = User(
        email="c-reports@x.com", full_name="Customer",
        password_hash=hash_password("Test#2026"),
        role="customer", status="active", email_verified=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": "Test#2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_my_reports_403_when_cap_off(client, provider_without_reports):
    """A provider whose cap is off (the default) gets 403 with the exact
    documented detail string — even if they somehow reached the endpoint
    (e.g. stale client, direct API call, race with an admin toggle)."""
    headers = _login(client, provider_without_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == (
        "Reports are not enabled for your account. Contact an administrator."
    )


def test_my_reports_200_when_cap_on(client, provider_with_reports):
    """Cap on → 200 with the trimmed response shape (no by_provider arrays)."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "period" in body
    assert "financial" in body and "by_month" in body["financial"]
    assert "operational" in body and "by_month" in body["operational"]
    # by_provider arrays MUST be trimmed — pointless for a single-provider view
    assert "by_provider" not in body["financial"]
    assert "by_provider" not in body["operational"]
    # Headline totals preserved
    assert "total_commission" in body["financial"]
    assert "total_bookings" in body["operational"]
    assert "total_passengers" in body["operational"]


def test_my_reports_default_period_last_6_months(client, provider_with_reports):
    """No from/to → default 6-month window (5 months ago through current)."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200, r.text
    period = r.json()["period"]
    # Both from and to are YYYY-MM strings; the span must be 6 months inclusive
    fy, fm = map(int, period["from"].split("-"))
    ty, tm = map(int, period["to"].split("-"))
    months = (ty - fy) * 12 + (tm - fm) + 1
    assert months == 6


def test_my_reports_respects_from_to(client, provider_with_reports):
    """Explicit from/to → response period reflects them."""
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine?from=2026-01&to=2026-03", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["period"] == {"from": "2026-01", "to": "2026-03"}


def test_my_reports_scoped_to_own_provider_id(client, db, provider_with_reports):
    """Even with two providers in the DB, /reports/mine only sees the caller's
    data. Uses a booking on a foreign provider to prove the scope filter is
    real, not vacuous."""
    from src.inventory.models import Trip
    from src.booking.models import Booking
    from datetime import datetime, timezone, timedelta

    # A DIFFERENT provider with confirmed booking activity in the current window.
    other = User(
        email="p-other@x.com", full_name="Other Provider",
        password_hash=hash_password("Test#2026"),
        role="provider", status="active", email_verified=True,
    )
    db.add(other); db.commit(); db.refresh(other)

    trip = Trip(
        provider_id=other.id,
        origin="Khartoum", destination="Port Sudan",
        departure_time=datetime.now(timezone.utc) + timedelta(days=3),
        price=100, seat_layout="45",
    )
    db.add(trip); db.commit(); db.refresh(trip)

    booking = Booking(
        trip_id=trip.id,
        status="confirmed",
        total_price=1000, channel="consumer",
        commission_amount=100,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(booking); db.commit()

    # Now call /reports/mine as provider_with_reports — should NOT see other's data.
    headers = _login(client, provider_with_reports.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # Caller has no bookings → totals stay zero
    assert body["financial"]["total_commission"] == 0
    assert body["operational"]["total_bookings"] == 0


def test_my_reports_401_when_unauth(client):
    """No Authorization header → 401 from the auth dependency."""
    r = client.get("/reports/mine")
    assert r.status_code == 401


def test_my_reports_403_when_customer(client, customer):
    """A customer hitting the endpoint gets 403 from the role guard —
    doesn't matter what their cap state is."""
    headers = _login(client, customer.email)
    r = client.get("/reports/mine", headers=headers)
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/reports/ -v
```

Expected: all 7 tests FAIL with 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Move the period helpers from admin/router.py to finance/reports.py**

In `backend/src/finance/reports.py`, append these two functions at the end of the module. Copy the exact behavior from `backend/src/admin/router.py:20-42` — same `_YYYY_MM` regex, same 24-month cap, same 6-month default:

```python
import re
from datetime import datetime
from fastapi import HTTPException

_YYYY_MM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_period(from_str: str, to_str: str) -> None:
    """Enforce the from/to YYYY-MM shape + ordering + 24-month cap.
    Raises HTTPException(400) on any violation. Moved from admin/router.py
    2026-07-28 to unify the period contract between admin and provider routes."""
    if not _YYYY_MM.match(from_str) or not _YYYY_MM.match(to_str):
        raise HTTPException(400, "from/to must be in YYYY-MM format")
    fy, fm = map(int, from_str.split("-"))
    ty, tm = map(int, to_str.split("-"))
    if (fy, fm) > (ty, tm):
        raise HTTPException(400, "from must be <= to")
    months = (ty - fy) * 12 + (tm - fm) + 1
    if months > 24:
        raise HTTPException(400, "Date range cannot exceed 24 months")


def default_period() -> tuple[str, str]:
    """Return the (from, to) YYYY-MM tuple for a 6-month window ending
    this month. Moved from admin/router.py 2026-07-28."""
    now = datetime.utcnow()
    m = now.month - 5
    y = now.year
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}", f"{now.year:04d}-{now.month:02d}"
```

Verify against the source at `backend/src/admin/router.py:20-42` before writing — if that function has any tweak this plan doesn't quote, preserve it verbatim.

- [ ] **Step 4: Delete the old helpers from admin/router.py and repoint callers**

In `backend/src/admin/router.py`:

1. Delete the `_YYYY_MM`, `_validate_period`, and `_default_period` definitions (lines ~20-42 pre-refactor — grep first to confirm).
2. Delete the `import re` line if it becomes unused; keep `from datetime import datetime as _dt` if any other code uses it (grep to confirm before removing).
3. At the two call sites (currently around lines 268-270 and 298-300), replace `_validate_period(from_, to)` with `finance_reports.validate_period(from_, to)` and `_default_period()` with `finance_reports.default_period()`. The module already imports finance_reports (grep for `finance_reports\|from ..finance` at the top of the file to confirm the exact alias).

- [ ] **Step 5: Create the reports package**

Create `backend/src/reports/__init__.py` (empty file).

Create `backend/src/reports/router.py`:

```python
"""Provider-scoped self-service reports.

Thin wrapper over finance.reports.build_reports. Caller is always a
provider (enforced by require_active_provider). Access is further gated
by the caller's own can_view_reports capability — 403 with an actionable
detail string when off. by_provider arrays are trimmed from the response
since a single provider looking at their own data doesn't need them.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import models
from ..auth.dependencies import require_active_provider
from ..database import get_db
from ..finance import reports as finance_reports

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/mine")
def my_reports(
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    provider: models.User = Depends(require_active_provider),
):
    if not provider.can_view_reports:
        raise HTTPException(
            status_code=403,
            detail="Reports are not enabled for your account. Contact an administrator.",
        )
    if not from_ or not to:
        d_from, d_to = finance_reports.default_period()
        from_ = from_ or d_from
        to = to or d_to
    finance_reports.validate_period(from_, to)
    payload = finance_reports.build_reports(
        db, from_str=from_, to_str=to, provider_id=provider.id,
    )
    # Trim the by_provider arrays — meaningless for a single-provider view.
    payload["financial"].pop("by_provider", None)
    payload["operational"].pop("by_provider", None)
    return payload
```

- [ ] **Step 6: Wire the router into the app**

In `backend/src/main.py`, find the `app.include_router(...)` block near where other routers are registered. Add:

```python
from .reports.router import router as reports_router
# ... (at the include_router block)
app.include_router(reports_router)
```

Match the existing include pattern — if the file already imports routers as `from .admin.router import router as admin_router` etc., follow that. If some other pattern is in use, follow it.

- [ ] **Step 7: Run the new tests to verify they pass**

```bash
cd backend && python -m pytest tests/reports/ -v
```

Expected: all 7 tests PASS.

- [ ] **Step 8: Run the full backend suite**

```bash
cd backend && python -m pytest -q
```

Expected: All tests pass. Baseline was 184 after Task 1; expect 191 after this task (+7).

- [ ] **Step 9: Commit**

```bash
git add backend/src/admin/router.py backend/src/finance/reports.py backend/src/reports/__init__.py backend/src/reports/router.py backend/src/main.py backend/tests/reports/__init__.py backend/tests/reports/test_my_reports.py
git commit -m "$(cat <<'EOF'
feat(reports): GET /reports/mine — provider self-service scope

New endpoint returns the caller's own by-month financial + operational
reports. Wraps the existing finance.reports.build_reports orchestrator
with provider_id hardcoded from the JWT (no cross-provider read
vector via crafted query params).

Response body is the admin /admin/reports shape minus the two
by_provider arrays (a single provider looking at their own data
doesn't need them). Headline totals — total_commission, total_bookings,
total_passengers — are preserved.

Gated by the caller's can_view_reports capability (added in Task 1)
plus the require_active_provider role guard. Off-cap 403s with a
specific detail string so the frontend can render actionable copy.

Also moves _validate_period + _default_period out of admin/router.py
into finance/reports.py (renamed validate_period / default_period) so
both admin and provider routes share the same period contract.

Seven new tests: cap-off 403, cap-on happy path, cross-provider scope,
default period, explicit period, unauth 401, customer-role 403.
EOF
)"
```

---

## Task 3: Frontend — admin toggle chip + provider Reports tab

**Files:**
- Modify: `frontend/index.html` — five discrete edits (admin cap chip markup + wiring, provider tab-bar markup + wiring, provider Reports panel markup, JS handlers + CSV export, EN + AR i18n keys).

**Interfaces:**
- Consumes: `PATCH /admin/providers/{id}/capabilities` (extended in Task 1), `GET /reports/mine` (Task 2), existing `api()` helper, `STATE.auth.user.can_view_reports`, `t()` i18n helper, `refreshProviderTab()`, `fmtMoney()` — all already present in `frontend/index.html`.
- Produces: new DOM ids `#cap-view-reports` (admin), `#provider-tab-reports` (provider tab-bar button), `#provider-reports-tab` (panel), `#pr-from`, `#pr-to`, `#pr-export`, `#pr-revenue-table`, `#pr-revenue-empty`, `#pr-activity-table`, `#pr-activity-empty`; new JS functions `refreshProviderReports()`, `renderRevenueTable()`, `renderActivityTable()`, `exportReportsCsv()`; 16 new i18n keys in EN + AR.

- [ ] **Step 1: Verify the exact JSON key names in the reports response**

Before writing render code, curl the deployed backend (or local) to confirm the key names on `by_month_financial` / `by_month_operational` rows. Grep `backend/src/finance/reports.py` for `return` or `buckets[m]` inside `financial_by_month` and `operational_by_month`:

```bash
grep -A 15 "def financial_by_month\|def operational_by_month" backend/src/finance/reports.py
```

Record the actual keys before writing the render functions. The spec sketched them as (financial: `month, commission, bookings, gross, net`) and (operational: `month, trips, seats, walkin, consumer`, plus `passengers` for the total), but the render functions must use whatever the module actually returns.

- [ ] **Step 2: Add the admin capability chip**

In `frontend/index.html`, find the Permissions section on the Admin Provider Detail page. Grep for `can_delete_trips` in the render code / handler — it should surface the existing three-chip block. Add a fourth chip in the same block, matching the exact style of the surrounding three:

- Same DOM structure (probably `<label class="cap-chip" data-cap="X"><input type="checkbox" id="cap-X"><span data-i18n="admin.provider.cap.Y">...</span></label>` — copy the pattern verbatim).
- Same JS wiring — grep for the click/change handler that reads the checkbox state and dispatches `PATCH /admin/providers/{id}/capabilities`. Extend it to also send `can_view_reports` when the fourth chip is toggled.

If the existing three chips are dynamically rendered from a list constant (e.g. `const CAPS = ['can_add_trips', 'can_edit_trips', 'can_delete_trips']`), add `'can_view_reports'` to that list — the render + wiring should then pick it up for free. Grep first before hand-writing the fourth chip.

- [ ] **Step 3: Add the provider Reports tab button + visibility gate**

Find the provider tab-bar block (grep for `provider-tab-mytrips` or `provider-tab-bookings`). Add a fourth tab button between "My Bookings" and "Support":

```html
<button class="tab-btn" data-tab="reports"
        id="provider-tab-reports"
        data-i18n="provider.tab.reports">Reports</button>
```

Inside `refreshProviderTab()` (or wherever the provider-home paints its chrome — grep to find it), add:

```javascript
const canReports = !!STATE.auth?.user?.can_view_reports;
$('#provider-tab-reports').hidden = !canReports;
```

If the currently-active tab is `reports` but the cap flipped off (e.g. an admin turned it off while the provider was mid-view), also fall back to the default tab:

```javascript
if (!canReports && currentTab === 'reports') switchProviderTab('mytrips');
```

Adapt `switchProviderTab` / `currentTab` to whatever the code actually calls them — grep before writing.

- [ ] **Step 4: Add the Reports panel markup**

Insert the panel next to the existing My Trips / My Bookings tab-content divs inside `#screen-provider-home`:

```html
<div id="provider-reports-tab" class="tab-content" hidden>
  <div class="reports-filter">
    <label><span data-i18n="admin.reports.from">From</span>:
      <input type="date" id="pr-from" />
    </label>
    <label><span data-i18n="admin.reports.to">To</span>:
      <input type="date" id="pr-to" />
    </label>
    <button class="btn-inline" id="pr-export" data-i18n="provider.reports.export">Export CSV</button>
  </div>

  <section class="pillow reports-section">
    <h3 data-i18n="provider.reports.revenue.title">Revenue</h3>
    <table class="report-table" id="pr-revenue-table"></table>
    <div class="empty-state hidden" id="pr-revenue-empty"
         data-i18n="provider.reports.revenue.empty">
      No revenue in this period yet.
    </div>
  </section>

  <section class="pillow reports-section">
    <h3 data-i18n="provider.reports.activity.title">Trip Activity</h3>
    <table class="report-table" id="pr-activity-table"></table>
    <div class="empty-state hidden" id="pr-activity-empty"
         data-i18n="provider.reports.activity.empty">
      No trip activity in this period yet.
    </div>
  </section>
</div>
```

Reuse the classes the admin Reports tab already uses (`.reports-filter`, `.reports-section`, `.report-table`, `.pillow`) — grep the admin panel first to confirm the class names.

- [ ] **Step 5: Add the JS handlers**

Find where `refreshProviderBookings` / `refreshProviderTrips` live and place the new handlers alongside:

```javascript
async function refreshProviderReports() {
  const from = $('#pr-from').value || undefined;
  const to   = $('#pr-to').value   || undefined;
  const qs   = new URLSearchParams();
  if (from) qs.set('from', from);
  if (to)   qs.set('to', to);
  const resp = await api('/reports/mine' + (qs.toString() ? '?' + qs : ''));
  renderRevenueTable(resp.financial?.by_month || []);
  renderActivityTable(resp.operational?.by_month || []);
}

function renderRevenueTable(rows) {
  const table = $('#pr-revenue-table');
  const empty = $('#pr-revenue-empty');
  if (!rows.length) {
    table.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  const head = `<thead><tr>
    <th data-i18n="provider.reports.col.month">Month</th>
    <th data-i18n="provider.reports.col.bookings">Bookings</th>
    <th data-i18n="provider.reports.col.gross">Gross</th>
    <th data-i18n="provider.reports.col.commission">Commission Deducted</th>
    <th data-i18n="provider.reports.col.net">My Net</th>
  </tr></thead>`;
  const body = rows.map(r => `<tr>
    <td>${escapeHtml(r.month)}</td>
    <td>${r.bookings}</td>
    <td class="num">SDG ${fmtMoney(r.gross || 0)}</td>
    <td class="num">SDG ${fmtMoney(r.commission || 0)}</td>
    <td class="num">SDG ${fmtMoney((r.gross || 0) - (r.commission || 0))}</td>
  </tr>`).join('');
  table.innerHTML = head + `<tbody>${body}</tbody>`;
  applyLanguage();  // re-translate the new [data-i18n] headers
}

function renderActivityTable(rows) {
  const table = $('#pr-activity-table');
  const empty = $('#pr-activity-empty');
  if (!rows.length) {
    table.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  const head = `<thead><tr>
    <th data-i18n="provider.reports.col.month">Month</th>
    <th data-i18n="provider.reports.col.trips">Trips</th>
    <th data-i18n="provider.reports.col.seats">Seats Sold</th>
    <th data-i18n="provider.reports.col.walkin">Walk-ins</th>
    <th data-i18n="provider.reports.col.consumer">Consumer</th>
  </tr></thead>`;
  const body = rows.map(r => `<tr>
    <td>${escapeHtml(r.month)}</td>
    <td>${r.trips ?? '—'}</td>
    <td>${r.passengers ?? r.seats ?? '—'}</td>
    <td>${r.walkin ?? '—'}</td>
    <td>${r.consumer ?? '—'}</td>
  </tr>`).join('');
  table.innerHTML = head + `<tbody>${body}</tbody>`;
  applyLanguage();
}
```

**Important:** the actual key names on rows (`r.gross`, `r.commission`, `r.trips`, `r.passengers`, `r.walkin`, `r.consumer`) must be verified against `finance/reports.py` in Step 1 of this task. If the module uses different keys, adjust the render accordingly. `r.gross - r.commission` may already be computed on the row (e.g. `r.net`) — prefer that if present.

Also verify `escapeHtml` and `fmtMoney` exist and match usage elsewhere in the file (grep first).

- [ ] **Step 6: Add CSV export**

```javascript
function exportReportsCsv() {
  const revRows = Array.from($('#pr-revenue-table').querySelectorAll('tbody tr'))
    .map(tr => Array.from(tr.children).map(td => td.textContent.trim()));
  const actRows = Array.from($('#pr-activity-table').querySelectorAll('tbody tr'))
    .map(tr => Array.from(tr.children).map(td => td.textContent.trim()));

  const csv = [
    'Revenue',
    'Month,Bookings,Gross,Commission Deducted,My Net',
    ...revRows.map(r => r.map(_csvEscape).join(',')),
    '',
    'Trip Activity',
    'Month,Trips,Seats Sold,Walk-ins,Consumer',
    ...actRows.map(r => r.map(_csvEscape).join(',')),
  ].join('\n');

  const now = new Date();
  const fname = `my-revenue-${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}.csv`;
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = fname;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}
```

`_csvEscape` should already exist in the file (used by admin CSV export + manifest CSV). If not, add a minimal:

```javascript
function _csvEscape(v) {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
```

- [ ] **Step 7: Wire the event handlers**

Find the existing `refreshProviderTrips` and `refreshProviderBookings` refresh triggers — usually a combination of tab-button click handler + input listeners on the filter strip. Add matching wiring for Reports:

```javascript
$('#pr-export')?.addEventListener('click', exportReportsCsv);

let _prDebounce = 0;
function _debouncedReportsRefresh() {
  clearTimeout(_prDebounce);
  _prDebounce = setTimeout(refreshProviderReports, 280);
}
$('#pr-from')?.addEventListener('input', _debouncedReportsRefresh);
$('#pr-to')?.addEventListener('input', _debouncedReportsRefresh);
```

Also ensure `refreshProviderReports()` fires once when the tab is switched to. If the tab-switcher already calls a per-tab refresh function (grep `refreshProviderTab` or `switchProviderTab`), add a `reports` branch that calls `refreshProviderReports()`.

- [ ] **Step 8: Add the EN i18n keys**

Locate the English `I18N.en` block. Find the `admin.reports.*` cluster (should already exist for the admin Reports tab). Add the new provider keys as a sibling cluster:

```javascript
    'provider.tab.reports': 'Reports',
    'provider.reports.revenue.title': 'Revenue',
    'provider.reports.revenue.empty': 'No revenue in this period yet.',
    'provider.reports.activity.title': 'Trip Activity',
    'provider.reports.activity.empty': 'No trip activity in this period yet.',
    'provider.reports.col.month': 'Month',
    'provider.reports.col.bookings': 'Bookings',
    'provider.reports.col.gross': 'Gross',
    'provider.reports.col.commission': 'Commission Deducted',
    'provider.reports.col.net': 'My Net',
    'provider.reports.col.trips': 'Trips',
    'provider.reports.col.seats': 'Seats Sold',
    'provider.reports.col.walkin': 'Walk-ins',
    'provider.reports.col.consumer': 'Consumer',
    'provider.reports.export': 'Export CSV',
    'admin.provider.cap.view_reports': 'Can view reports',
```

- [ ] **Step 9: Add the AR i18n keys**

Locate the Arabic `I18N.ar` block. Add the matching AR keys:

```javascript
    'provider.tab.reports': 'التقارير',
    'provider.reports.revenue.title': 'الإيرادات',
    'provider.reports.revenue.empty': 'لا يوجد إيرادات في هذه الفترة بعد.',
    'provider.reports.activity.title': 'نشاط الرحلات',
    'provider.reports.activity.empty': 'لا يوجد نشاط رحلات في هذه الفترة بعد.',
    'provider.reports.col.month': 'الشهر',
    'provider.reports.col.bookings': 'الحجوزات',
    'provider.reports.col.gross': 'الإجمالي',
    'provider.reports.col.commission': 'العمولة المخصومة',
    'provider.reports.col.net': 'صافي إيراداتي',
    'provider.reports.col.trips': 'الرحلات',
    'provider.reports.col.seats': 'المقاعد المباعة',
    'provider.reports.col.walkin': 'حجوزات المنفذ',
    'provider.reports.col.consumer': 'حجوزات إلكترونية',
    'provider.reports.export': 'تصدير CSV',
    'admin.provider.cap.view_reports': 'يمكنه عرض التقارير',
```

- [ ] **Step 10: JS syntax gate**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output (success). This is a hard gate — a syntax error in the inline `<script>` bricks the entire SPA. The project has been bitten before.

- [ ] **Step 11: Backend regression check**

```bash
cd backend && python -m pytest -q
```

Expected: 191 passing (unchanged from Task 2 baseline — this task doesn't touch backend).

- [ ] **Step 12: Manual smoke test — admin toggle → provider tab appears**

Serve the frontend against the deployed backend (or local). Sign in as admin, navigate to Provider Detail for one of the seeded providers (Nile Coach Co. or SudanBus Express). In the Permissions section, verify:

1. Four capability chips are visible; the fourth is "Can view reports" and defaults OFF.
2. Toggle it ON → chip visually flips to amber-active → check network tab: a `PATCH /admin/providers/{id}/capabilities` request went out with `{"can_view_reports": true}` in the body.
3. Sign out; sign back in as that provider (`operator@tazkirati.app` / `NileOps#2026` for Nile Coach, or the SudanBus creds).
4. Provider tab-bar shows a "Reports" tab between "My Bookings" and "Support".
5. Click Reports → two tables load (or two empty-state messages if the seed data has no confirmed bookings for that provider in the last 6 months — that's expected).
6. Column headers read exactly "Commission Deducted" and "My Net" (NOT "Commissions Earned" or "Net Payout").
7. Change from/to → tables refresh after ~280 ms debounce.
8. Click Export CSV → file `my-revenue-YYYY-MM.csv` downloads. Open it — Revenue block first, blank row, Trip Activity block after.
9. Sign out; sign back in as admin; toggle the cap OFF → sign back in as provider → Reports tab is gone.

- [ ] **Step 13: Manual smoke test — Arabic + RTL**

Still signed in as the provider (cap on), toggle language to Arabic. Confirm:

1. Tab reads "التقارير".
2. Section titles read "الإيرادات" and "نشاط الرحلات".
3. Column headers "العمولة المخصومة" and "صافي إيراداتي" appear (NOT the admin-namespace strings).
4. Direction is RTL; numeric cells stay LTR internally.
5. CSV export still works; the header rows may show mojibake in Excel without the BOM — the code prepends `﻿` so this should be clean.

- [ ] **Step 14: Manual smoke test — admin-side copy stays platform-voice**

Sign in as admin, open the Reports tab in the admin console AND the per-provider Reports drilldown on Provider Detail. Confirm the column labels there STILL read "Commissions Earned" and "Net Payout" (or whatever the admin admin.reports.* keys currently render). The provider-side keys must not have leaked into the admin surface.

- [ ] **Step 15: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(v2): provider self-service Reports tab

Fourth capability chip on the admin Provider Detail page toggles the
new can_view_reports flag. When on, the affected provider sees a
"Reports" tab in their tab-bar between "My Bookings" and "Support",
rendering two pillow-styled by-month tables (Revenue, Trip Activity)
with a from/to filter (280ms debounced) and client-side CSV export.

Copy is reworded for the operator voice — "Revenue" not "Financial",
"Commission Deducted" not "Commissions Earned", "My Net" not "Net
Payout". Admin's own Reports tab and per-provider drilldown are
unchanged — the platform-voice copy is intentional there.

Fetches GET /reports/mine (Task 2). Cap OFF hides the tab entirely.
16 new i18n keys × EN + AR.
EOF
)"
```

---

## Verification (post-all-tasks)

- [ ] **Backend suite green**

```bash
cd backend && python -m pytest -q
```

Expected: 191 passing (was 182 before this plan; Task 1 adds 2, Task 2 adds 7).

- [ ] **Frontend JS syntax check**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output.

- [ ] **Deploy**

Push to `feat/mobile-scaffold` (Render auto-deploys). Wait for "Deploy live" in the Render dashboard.

- [ ] **Deployed smoke sweep**

1. As admin: toggle a seeded provider's cap on, then off → notification bell on the provider side pings both times.
2. As that provider: Reports tab appears when cap is on, disappears when cap is off.
3. Reports render with the correct operator-voice copy in EN + AR.
4. CSV export downloads with the expected filename + UTF-8 BOM.

- [ ] **Update CLAUDE.md**

Add a "Recent fixes" entry at the top of that section summarizing what shipped: date, endpoint, capability flag, admin-toggle location, provider-side location, i18n keys added, the deliberate default-OFF deviation, and the copy-reframing decision.

```bash
git add claude.md
git commit -m "docs: log provider Reports self-service ship in CLAUDE.md"
```
