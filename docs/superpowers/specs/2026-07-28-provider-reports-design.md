# Provider Reports (Self-Service, Gated) — Design Spec

**Date:** 2026-07-28
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)
**Branch:** `feat/mobile-scaffold`
**Related:** Provider capability toggles landed 2026-07-13 (`can_add_trips` / `can_edit_trips` / `can_delete_trips`); admin Reports tab landed 2026-06-23; per-provider Reports drilldown on the Provider Detail page landed 2026-07-23. This spec adds the FIRST provider-facing view of the same data.

## 1. Goal

Let an admin flip a per-provider capability that reveals a "Reports" tab in that provider's own tab bar. The tab shows the same financial + operational aggregates the admin sees for that provider — reworded to speak in the operator's voice ("Revenue", "Platform Commission", "My Net") instead of the platform's ("Financial", "Commissions Earned", "Net Payout"). The number underneath is identical; the framing is not.

The cap is opt-in per provider — a new provider gets no Reports tab until the admin flips the switch. This is a **deliberate one-off deviation** from the existing three capability flags (`can_add_trips`, `can_edit_trips`, `can_delete_trips`), which all default to TRUE because they enable core provider workflows. Revenue visibility is more sensitive — not every operator wants their walk-in staff seeing net numbers — so we default OFF.

## 2. Out of scope

- **Fine-grained sub-capabilities.** One toggle gates the whole tab. No separate "can view financial only" / "can view operational only" splits.
- **Provider-scoped audit log.** The `audit_events` table records admin-side actions today; giving a provider read access to their own audit trail is a separate feature.
- **Commission-campaign visibility.** Base commission (`bookings.commission_amount` at confirm time, per the 2026-06-21 commissions ship) is all that is aggregated today; time-windowed campaigns are still deferred (V2 backlog).
- **Reports for admins.** The admin Reports tab and the per-provider Reports drilldown on the Provider Detail page BOTH stay exactly as-is. Admin-facing copy still reads in platform voice — "Financial" / "Commissions Earned" / "Net Payout".
- **Cross-provider comparison for a provider.** A provider sees their own numbers only. No leaderboard, no "you vs. others".
- **Push-to-email / scheduled exports.** CSV download stays client-side Blob only, same as the admin export.
- **Provider notification of "your reports were just viewed by an admin".** Not a real product need.
- **Mobile-native surface.** Uses the same pillow web view via Capacitor — no separate iOS/Android layout.

## 3. Architecture overview

```
                         ┌────────────────────────────────────┐
                         │  users table                        │
                         │    can_view_reports Boolean         │
                         │    NOT NULL DEFAULT FALSE           │
                         └──────────────▲──────────────────────┘
                                        │  PATCH .../capabilities
                                        │  (existing endpoint, extended)
                                        │
             admin: Provider Detail ──> Permissions section ──> 4th toggle chip
                                        │
                                        │  emits provider_capability_changed
                                        │  (existing notification)
                                        ▼
             provider: STATE.auth.user.can_view_reports flips true
                                        │
                                        ▼
             provider tab-bar: renders 4th tab "Reports" between
             "My Bookings" and "Support"
                                        │
                                        │  click
                                        ▼
                         ┌────────────────────────────────────┐
                         │  GET /reports/mine?from=&to=       │
                         │  Depends(require_active_provider)   │
                         │  + explicit cap check → 403 if off  │
                         │                                     │
                         │  Uses finance.reports.build_reports │
                         │  (existing) with provider_id = self │
                         │                                     │
                         │  Response trimmed to 2 arrays:      │
                         │    by_month_financial               │
                         │    by_month_operational             │
                         └─────────────────────────────────────┘
```

Nothing in the aggregation logic changes. The `finance/reports.py` functions already accept an optional `provider_id` filter (used by the admin drilldown at `GET /admin/providers/{id}/reports`) — we're wrapping them behind a new caller-scoped router.

## 4. Backend

### 4.1 Schema — new column on `users` (`backend/src/auth/models.py`)

```python
class User(Base):
    ...
    can_add_trips = Column(Boolean, nullable=False, server_default=text("TRUE"))
    can_edit_trips = Column(Boolean, nullable=False, server_default=text("TRUE"))
    can_delete_trips = Column(Boolean, nullable=False, server_default=text("TRUE"))
    can_view_reports = Column(Boolean, nullable=False, server_default=text("FALSE"))
```

Migration in `backend/src/database.py :: _migrate_if_needed()`:

```python
db.execute(text(
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_reports BOOLEAN NOT NULL DEFAULT FALSE"
))
```

**Note:** every existing provider row picks up FALSE at migration time. This is the intended state — admins opt providers in explicitly after the ship lands.

### 4.2 Capability update endpoint

Existing schema is `ProviderCapabilitiesUpdate` in `backend/src/admin/schemas.py`. Add one optional field:

```python
class ProviderCapabilitiesUpdate(BaseModel):
    can_add_trips: Optional[bool] = None
    can_edit_trips: Optional[bool] = None
    can_delete_trips: Optional[bool] = None
    can_view_reports: Optional[bool] = None
```

Existing router handler at `backend/src/admin/router.py:85-101` currently passes three named args to `service.update_provider_capabilities`. Add the fourth:

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

Extend `service.update_provider_capabilities` (in `backend/src/admin/service.py`) with the matching keyword arg + branch. The existing notification emit (`provider_capability_changed`) fans out any changed fields as a JSON payload keyed by capability name — no changes needed there.

### 4.3 New reports router + shared period helpers

Two period helpers currently live in `backend/src/admin/router.py:23-38` — `_validate_period(from_str, to_str)` and `_default_period()`. Because the new provider endpoint needs the same behavior, move both into `backend/src/finance/reports.py` (rename to top-level `validate_period` / `default_period` — no underscore, they're now part of the module's public surface) and update the two admin call sites at `router.py:268-271` and `router.py:298-301` to import from `finance.reports`. This is a small refactor that unifies the period-handling contract; no behavior change.

New package `backend/src/reports/` (`__init__.py`, `router.py`). No models, no service — pure orchestration.

```python
# backend/src/reports/router.py
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
    """Provider-scoped reports (financial + operational).

    Requires the caller's can_view_reports capability. When the cap is off
    the endpoint 403s with an actionable message — the frontend should not
    surface the Reports tab in that state, but we defend at the router in
    case of a stale client, direct API call, or race with an admin toggle.
    """
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
    # Trim by-provider arrays — pointless for a single-provider view.
    payload["financial"].pop("by_provider", None)
    payload["operational"].pop("by_provider", None)
    return payload
```

Wire it in `backend/src/main.py` — add one `app.include_router(reports_router)` line next to the existing routers.

**Response shape** matches the admin `/admin/reports` route minus the two `by_provider` arrays. Headline totals (`total_commission`, `total_bookings`, `total_passengers`) are preserved so the operator can render a summary strip if desired.

**No cross-provider read vector.** `provider_id=provider.id` is the JWT-authenticated caller's id. The endpoint does not accept a `provider_id` query param — a crafted request cannot reach another provider's data.

### 4.4 Tests (`backend/tests/reports/test_my_reports.py`, new)

Seven cases mirroring the admin drilldown tests but scoped to the caller:

1. `test_my_reports_403_when_cap_off` — active provider with `can_view_reports=False` (the default) gets 403 with the exact detail string.
2. `test_my_reports_200_when_cap_on` — active provider with `can_view_reports=True` gets a 200 response containing both `by_month_financial` and `by_month_operational` arrays.
3. `test_my_reports_scoped_to_own_provider_id` — seed bookings for two providers (A + B), sign in as A with cap on, verify the response reflects only A's data (row counts + summed amounts) — even if A were to somehow include a `provider_id=B` query param, it must not surface B's data.
4. `test_my_reports_default_period_last_6_months` — no `from`/`to` supplied → response `period` field spans the last 6 months (uses the same `_resolve_period` helper the admin route uses).
5. `test_my_reports_respects_from_to` — explicit `from` + `to` → response `period` reflects them.
6. `test_my_reports_401_when_unauth` — no auth header → 401. Ensures `require_active_provider` guard fires.
7. `test_my_reports_403_when_customer` — customer role (with any cap state) hits the endpoint → 403 from the role guard, not the cap guard.

Plus two extension tests on the capability endpoint (`backend/tests/admin/test_capabilities.py` or wherever the existing capability tests live):

8. `test_capabilities_patch_accepts_can_view_reports` — admin PATCH with `{"can_view_reports": true}` flips the flag on the target provider.
9. `test_new_provider_defaults_can_view_reports_false` — seed a fresh provider, assert `provider.can_view_reports is False`. Locks the default.

## 5. Frontend — provider side

### 5.1 Tab-bar entry

In the provider tab-bar section of `frontend/index.html` (currently renders "My Trips" / "My Bookings" / "Support"), add a fourth tab between "My Bookings" and "Support":

```html
<button class="tab-btn" data-tab="reports"
        id="provider-tab-reports"
        data-i18n="provider.tab.reports">Reports</button>
```

Visibility gate — the tab is hidden when the cap is off. Toggled inside `refreshProviderTab()` (which fires on every provider-home entry + refresh):

```javascript
const canReports = !!STATE.auth?.user?.can_view_reports;
$('#provider-tab-reports').hidden = !canReports;
```

No error state, no locked-lock icon. If the admin has not enabled reports, the tab simply does not exist for that user session.

### 5.2 Reports panel

New section inside `#screen-provider-home` (mirrors the structure of the existing `#provider-mytrips-tab` / `#provider-mybookings-tab` panels):

```html
<div id="provider-reports-tab" class="tab-content" hidden>
  <div class="reports-filter">
    <label>From: <input type="date" id="pr-from" /></label>
    <label>To:   <input type="date" id="pr-to"   /></label>
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

Reuses the pillow report-table primitives already defined for the admin Reports tab (`.report-table`, `.reports-section`, `.reports-filter`) — no new CSS shape.

### 5.3 Fetch + render

Wire on tab-click (matches the pattern used by My Trips / My Bookings):

```javascript
async function refreshProviderReports() {
  const from = $('#pr-from').value || undefined;
  const to   = $('#pr-to').value   || undefined;
  const qs   = new URLSearchParams();
  if (from) qs.set('from', from);
  if (to)   qs.set('to', to);
  const resp = await api('/reports/mine' + (qs.toString() ? '?' + qs : ''));
  // Response shape matches the admin /admin/reports payload minus the
  // by_provider arrays — see spec §4.3.
  renderRevenueTable(resp.financial?.by_month || []);
  renderActivityTable(resp.operational?.by_month || []);
}
```

`renderRevenueTable` builds a table with columns: Month · Bookings · Gross · Commission Deducted · My Net. `renderActivityTable` builds: Month · Trips · Seats Sold · Walk-ins · Consumer. Both empty-state fall through to their `.empty-state` div when the array is empty.

**Column keys — verify against `finance/reports.py`** when implementing. `financial_by_month` returns `{month, commission, bookings, ...}` rows; `operational_by_month` returns different keys. The exact key names must be pulled from the module during implementation — don't assume them from the column labels above.

280 ms debounce on the from/to filter inputs (matches admin Reports + provider trips/bookings filters).

### 5.4 CSV export

Client-side Blob download, filename `my-revenue-YYYY-MM.csv` (where `YYYY-MM` is today). UTF-8 BOM prepended so Excel opens Arabic month names correctly. Two files aren't needed — bundle both tables into one CSV with a blank row + header separator between them, matching the pattern used elsewhere in the app.

### 5.5 i18n (new `provider.reports.*` namespace)

~14 new keys in both `I18N.en` and `I18N.ar`:

| Key | English | Arabic |
|---|---|---|
| `provider.tab.reports` | Reports | التقارير |
| `provider.reports.revenue.title` | Revenue | الإيرادات |
| `provider.reports.revenue.empty` | No revenue in this period yet. | لا يوجد إيرادات في هذه الفترة بعد. |
| `provider.reports.activity.title` | Trip Activity | نشاط الرحلات |
| `provider.reports.activity.empty` | No trip activity in this period yet. | لا يوجد نشاط رحلات في هذه الفترة بعد. |
| `provider.reports.col.month` | Month | الشهر |
| `provider.reports.col.bookings` | Bookings | الحجوزات |
| `provider.reports.col.gross` | Gross | الإجمالي |
| `provider.reports.col.commission` | Commission Deducted | العمولة المخصومة |
| `provider.reports.col.net` | My Net | صافي إيراداتي |
| `provider.reports.col.trips` | Trips | الرحلات |
| `provider.reports.col.seats` | Seats Sold | المقاعد المباعة |
| `provider.reports.col.walkin` | Walk-ins | حجوزات المنفذ |
| `provider.reports.col.consumer` | Consumer | حجوزات إلكترونية |
| `provider.reports.export` | Export CSV | تصدير CSV |

Numeric table cells force `dir="ltr"` under RTL, matching the admin Reports pattern.

**Explicit deviation from admin copy:** the admin's `admin.reports.col.commission` reads "Commissions Earned" (platform-voice). The provider's `provider.reports.col.commission` reads "Commission Deducted" (operator-voice). Same underlying number; different framing. Same principle for `provider.reports.col.net` reading "My Net" (take-home) instead of "Net Revenue".

## 6. Frontend — admin side

### 6.1 Fourth capability toggle on the Provider Detail page

Existing pattern in the Permissions section renders three amber-pill chips (Can Add Trips / Can Edit Trips / Can Delete Trips). Add a fourth:

```html
<label class="cap-chip" data-cap="can_view_reports">
  <input type="checkbox" id="cap-view-reports">
  <span data-i18n="admin.provider.cap.view_reports">Can view reports</span>
</label>
```

Toggling fires the existing `PATCH /admin/providers/{id}/capabilities` handler (same as the other three chips). No new endpoint, no new toast, no new confirmation dialog.

### 6.2 i18n additions (admin namespace)

Just two new keys:

| Key | English | Arabic |
|---|---|---|
| `admin.provider.cap.view_reports` | Can view reports | يمكنه عرض التقارير |
| (admin's own Reports tab copy stays unchanged) | | |

## 7. Access control

Belt-and-braces. Two independent guards must both pass for a provider to see numbers:

1. **Frontend visibility.** `#provider-tab-reports.hidden = !STATE.auth.user.can_view_reports` — a session that never sees the tab can't click into it.
2. **Backend cap check.** `GET /reports/mine` returns 403 when `provider.can_view_reports` is False, regardless of what the frontend sent. Defends against a stale client, a direct API call, or a race where the admin toggled the cap off mid-session.

The scope enforcement is separate again: `provider_id=provider.id` is hardcoded from the JWT-authenticated `require_active_provider` dependency. No query-parameter injection can reach a different provider's data.

## 8. Rollout notes

- Neon migration is idempotent (`ADD COLUMN IF NOT EXISTS`); existing rows pick up FALSE.
- No env var changes.
- No mobile-specific work — Capacitor loads the same `frontend/index.html` via `webDir: ../frontend`.
- Existing providers see no change until an admin toggles their cap.
- Admin's own Reports tab and Provider Detail Reports drilldown are unchanged (rendered content, labels, endpoints all identical).

## 9. Success criteria

1. A newly-approved provider has `can_view_reports = False` and sees no Reports tab.
2. Admin toggles the cap on via the Provider Detail Permissions section → the affected provider gets a `provider_capability_changed` notification → on next `refreshProviderTab()` the Reports tab appears.
3. Provider clicks Reports → sees two by-month tables (Revenue, Trip Activity). Column headers read "Commission Deducted" and "My Net" in English; "العمولة المخصومة" and "صافي إيراداتي" in Arabic.
4. Provider changes from/to filters → tables refresh (280 ms debounce). Empty period → empty-state message.
5. Provider clicks Export CSV → file `my-revenue-2026-07.csv` downloads with UTF-8 BOM. Both tables inside one file.
6. Admin's own Reports tab still says "Financial" / "Commissions Earned" / "Net Payout" — no accidental copy leak from the provider namespace.
7. Attempting `GET /reports/mine` while cap is off (either via stale client or direct curl) → 403 with the documented detail string. Never a 500, never a leak of another provider's data.
8. Backend tests (7 new in the reports module + 2 in the capabilities module) all pass. Suite was 182 after the Personal Information ship; expect 191 after this.
