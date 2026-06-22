# Reports — Design Spec

**Date:** 2026-06-23
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)

## 1. Goal

Admin-facing reporting in the existing admin panel, with two stacked sections:

1. **Financial** — how much commission the platform earned, bucketed by month and by provider.
2. **Operational** — how many bookings + passengers moved through the system, bucketed by month and by provider, split by channel (consumer vs walk-in).

Both sections share a single filter strip (date range + provider). Each table is independently CSV-exportable.

This replaces the deferred "Financial / operational reports (3.6–3.7)" item from CLAUDE.md.

## 2. Out of scope

- Real-time dashboards / live-updating charts. Reports load on demand, no polling.
- Charts or visualisations. Tables only.
- Per-trip rollup. The smallest unit is provider-per-month.
- Drill-down (clicking a row to see underlying bookings). Deferred; admin already has `/admin/bookings` with filters for that purpose.
- Provider-facing reports. Providers see per-row commission + a totals footer on their existing Bookings tab (already shipped). They don't get the admin Reports view.
- Year-over-year, week-over-week, day-bucket variants. Month is the only bucket.
- Currency display in anything other than en-US digits ("SDG 14,750"). Existing project convention.

## 3. Time-bucket basis

**All buckets are by confirmation date** — when the booking transitioned from `committed_pending → confirmed` (admin or provider cash). Rationale:

- Financial reports answer "how much commission landed in June" — accounting reality.
- Operational reports answer "how many transactions cleared in June" — operations reality.
- Trip departure date is intentionally **not** the basis. A booking confirmed in June for a July departure shows in June.
- Booking creation date is also not the basis. A booking locked in May and confirmed in June shows in June.

The single date basis keeps the UI mental model simple ("everything in this report is keyed to when money cleared").

## 4. Data model — `confirmed_at`

Add **one nullable column** to `bookings`:

```
confirmed_at  TIMESTAMP NULLABLE
```

Populated in two places:

1. **Going forward**: `admin.service.confirm_payment()` sets `booking.confirmed_at = _now_utc_naive()` before commit. Single hook covers both admin-confirmed and provider walk-in cash-confirmed paths (same shared call site as the commission snapshot, per `cdb7fc4`).

2. **Backfill once**: `_migrate_if_needed()` runs an idempotent `ALTER TABLE bookings ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP` followed by a one-shot backfill statement:
   ```sql
   UPDATE bookings
   SET confirmed_at = COALESCE(bill_generated_at, created_at)
   WHERE status = 'confirmed' AND confirmed_at IS NULL
   ```
   `bill_generated_at` is the closest proxy on the consumer-channel path (set at billing intent, ~minutes before confirmation). For cash walk-ins where billing was minted at confirm time, it's even closer. For bookings without billing reference at all, `created_at` is the fallback. The backfill is bounded by `confirmed_at IS NULL` so re-runs are no-ops.

No other schema change. The report aggregations use `trip.provider_id`, `booking.commission_amount`, `booking.total_price`, `booking.channel`, `booking.status`, `booking.confirmed_at`, plus a join to `User` for provider name.

## 5. Backend — single endpoint

`GET /admin/reports` mounted on the existing admin router. Admin-only (existing `require_admin` dependency).

### Query parameters

| param | type | default | semantics |
|---|---|---|---|
| `from` | string `YYYY-MM` | 5 months ago (so 6 months including current) | Inclusive month start. Backend converts to `YYYY-MM-01 00:00:00` UTC. |
| `to` | string `YYYY-MM` | current month | Inclusive month end. Backend converts to the last instant of that month. |
| `provider_id` | int (optional) | all providers | Narrows both Financial and Operational aggregations to one provider. |

Validation:
- `from` and `to` must match `^\d{4}-\d{2}$` and be valid year-month combinations.
- `from <= to` required (400 otherwise).
- Date range cap: max 24 months (refuse with 400 otherwise — keeps query cost predictable).

### Response shape

```json
{
  "period": {
    "from": "2026-01",
    "to":   "2026-06"
  },
  "financial": {
    "total_commission": 14750.0,
    "by_month": [
      {"month": "2026-01", "commission": 1200.0, "bookings": 3},
      {"month": "2026-02", "commission": 0.0,    "bookings": 0},
      {"month": "2026-03", "commission": 3050.0, "bookings": 8},
      ...
    ],
    "by_provider": [
      {"provider_id": 3, "provider_name": "Nile Coach Co.",  "commission": 8500.0, "bookings": 12},
      {"provider_id": 4, "provider_name": "SudanBus Express", "commission": 6250.0, "bookings": 7}
    ]
  },
  "operational": {
    "total_bookings":   47,
    "total_passengers": 89,
    "by_month": [
      {"month": "2026-01", "bookings": 12, "passengers": 22, "consumer": 8, "walkin": 4},
      ...
    ],
    "by_provider": [
      {"provider_id": 3, "provider_name": "Nile Coach Co.",  "bookings": 28, "passengers": 51, "consumer": 19, "walkin": 9},
      ...
    ]
  }
}
```

### Aggregation rules

All aggregations restrict to:
- `status = 'confirmed'`
- `confirmed_at` between the period start (inclusive) and end (inclusive)
- `trip.provider_id = provider_id` if the filter is set

**Financial sums** (`total_commission`, `by_month[].commission`, `by_provider[].commission`):
- Skip rows where `commission_amount IS NULL` — these are bookings confirmed before the commission feature shipped. They contributed zero to platform earnings; including them as zeros would be honest but pollutes the row count. We exclude them entirely from the financial side.
- Walk-in rows have `commission_amount = 0.0` (not NULL) so they're included in `bookings` count but contribute 0 to the sum. This is intentional — walk-ins still count as "platform-recorded transactions with a known zero commission."

**Operational counts** (`total_bookings`, `total_passengers`, the `by_month` / `by_provider` arrays):
- Include all confirmed rows, regardless of `commission_amount`. Historic pre-commission bookings are real transactions.
- `passengers` = sum of `len(booking.passengers)` aggregated per group.
- `consumer` and `walkin` are booking counts split by `booking.channel`.

**Empty months**: `by_month` includes one row per month in the range, even months with zero activity. This makes the UI predictable (a 6-month report has 6 rows, sorted oldest first). The frontend doesn't need to "fill the gaps."

**Empty providers**: `by_provider` only includes providers with **at least one row** in the period. A provider with zero bookings in the range doesn't appear (vs months, which always appear because the month axis is intrinsic to the report).

### Implementation file layout

- New file: `backend/src/finance/reports.py` — pure functions:
  - `period_months(from_str, to_str) -> list[str]` — returns `["2026-01", ..., "2026-06"]`
  - `financial_by_month(db, *, period, provider_id) -> list[dict]`
  - `financial_by_provider(db, *, period, provider_id) -> list[dict]`
  - `operational_by_month(db, *, period, provider_id) -> list[dict]`
  - `operational_by_provider(db, *, period, provider_id) -> list[dict]`
  - `build_reports(db, *, from_str, to_str, provider_id) -> dict` — composes the response

The router endpoint is **8–15 lines**: parse query params, call `build_reports`, return the dict. Aggregation lives in `reports.py`, not the router.

Rationale for a separate file (not `finance/service.py`): `service.py` holds the resolver + snapshot + admin CRUD for commission rules. Mixing report aggregation there muddies the responsibility. Reports compose data the service produced; they don't manage rules.

## 6. Frontend — new admin tab

A **fifth tab** in the admin home tab strip: **Reports**. Live alongside Providers / Trips / Bookings / Payments.

### Markup placement

Inside the existing `<div class="tab-bar admin-tabs">` block, add a button. Inside the existing tab-content panel grid, add `<div data-tab-panel="reports">` with the report markup.

### Layout (within the tab panel)

**Filter strip** (mirrors the existing booking-filter pattern — auto-applies with debounce, no Apply button):
- `From` input — `type="month"` (native browser picker), default `YYYY-MM` for "5 months ago"
- `To` input — `type="month"`, default current `YYYY-MM`
- `Provider` `<select>` — first option is "All providers", remaining options pulled from `/admin/providers?status=active`
- Any change to the three controls triggers a 280ms debounced fetch — matching the booking-filter strip already in production. No explicit Apply button.

**Financial section**:
- Headline card: large number, "SDG 14,750 commission earned" + small subtitle showing the active period
- "By month" panel with table + per-table Export CSV button
  - Columns: Month | Commission (SDG) | Booking count
- "By provider" panel with table + per-table Export CSV button
  - Columns: Provider | Commission (SDG) | Bookings

**Operational section**:
- Two headline numbers side-by-side: "47 bookings" and "89 passengers"
- "By month" panel with table + Export CSV
  - Columns: Month | Bookings | Passengers | Consumer | Walk-in
- "By provider" panel with table + Export CSV
  - Columns: Provider | Bookings | Passengers | Consumer | Walk-in

Tables use the existing `.panel` / `.booking-row` pattern where it fits. Where tabular density matters more, a real `<table>` with `.report-table` class. Per-row hover highlight; alternating row backgrounds via `tr:nth-child(even)`.

### CSV export

Client-side generation. Each Export CSV button:
1. Reads the relevant array from the cached response JSON.
2. Builds a CSV with a header row matching the visible column labels (using `t()` for i18n consistency).
3. Triggers a download via `Blob` + `<a download>` with filename like:
   ```
   tazkirati-financial-by-month-2026-01-to-2026-06.csv
   tazkirati-financial-by-provider-2026-01-to-2026-06.csv
   tazkirati-operational-by-month-2026-01-to-2026-06.csv
   tazkirati-operational-by-provider-2026-01-to-2026-06.csv
   ```
   When a `provider_id` filter is active, append `-providerN` to the filename so files with different filters don't overwrite each other.
4. Numeric cells use en-US digits (period as decimal, no thousands separator in CSV — Excel handles that). Month strings are quoted as `"2026-01"`. Currency is unprefixed numbers (CSV is data, not display).

No server-side CSV endpoint. The data is already in the response; the browser can build the file.

### Mobile (≤640px)

Tables collapse to **stacked cards**. One card per row, headline metric first, secondary metrics below in smaller mono type:

```
┌─────────────────────────┐
│ 2026-03                 │
│ SDG 3,050  · 8 bookings │
└─────────────────────────┘
```

Filter strip collapses to a single column (the existing `grid-template-columns: 1fr` rule under `@media max-width: 880px` already covers this for `.filter-strip`). The new Reports CSS adds the table-to-card collapse for `.report-table` and friends.

The fifth admin tab fits in the existing fixed-bottom tab bar on mobile because that bar uses `flex: 1` per tab — five icons gets cramped but tolerable. CLAUDE.md notes the bar is for Providers / Trips / Bookings / Payments + now Reports; we accept slight crowding for the demo.

### i18n keys (~20 new)

Under `admin.reports.*`:
- `admin.reports.tab` — "Reports" / "التقارير"
- `admin.reports.filter.from` / `.to` / `.provider` / `.apply` / `.allProviders`
- `admin.reports.financial.title` — "Financial" / "المالي"
- `admin.reports.financial.headline` — "Commission earned" / "العمولة المُحصَّلة"
- `admin.reports.financial.bymonth` / `.byprovider`
- `admin.reports.operational.title` — "Operational" / "العملي"
- `admin.reports.operational.bookings` / `.passengers` / `.consumer` / `.walkin`
- `admin.reports.col.month` / `.col.provider` / `.col.commission` / `.col.bookings` / `.col.passengers`
- `admin.reports.export.csv` — "Export CSV" / "تصدير CSV"
- `admin.reports.empty` — "No activity in the selected range." / "لا نشاط في الفترة المختارة."

Both EN and AR. Currency strings ("SDG") stay untranslated for receipt clarity per project convention.

## 7. Migration

Three changes ship together in the same `_migrate_if_needed()` invocation:

1. `ALTER TABLE bookings ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP` — idempotent, safe on every boot.
2. Backfill: `UPDATE bookings SET confirmed_at = COALESCE(bill_generated_at, created_at) WHERE status = 'confirmed' AND confirmed_at IS NULL` — populates historic confirmed bookings. Bounded by the `IS NULL` clause so re-runs do nothing on already-populated rows.
3. Optional index for query performance: `CREATE INDEX IF NOT EXISTS idx_bookings_confirmed_at ON bookings (confirmed_at)`. Reports filter on this column; an index pays for itself at modest scale.

The migration runs **before** `_bootstrap_if_empty()` (same ordering as the commission column migration), so the very first deploy populates the column on whatever seed.py creates.

## 8. Testing

New test file: `backend/tests/finance/test_reports.py`. Covers:

1. **Empty period** — no confirmed bookings in range → response has zero totals, `by_month` is a list of 6 zero rows, `by_provider` is empty list.
2. **One booking** — places a single confirmed booking with known commission; verifies it lands in the right month bucket and the right provider row.
3. **Walk-in vs consumer split** — confirms a walk-in adds to `bookings` and `walkin` count, contributes 0 to commission. Confirms a consumer booking with a rule contributes to commission.
4. **Historic NULL-commission booking** — confirmed booking with `commission_amount IS NULL` (simulating pre-feature data). Operational counts it; financial excludes it.
5. **Provider filter** — passing `provider_id` narrows both sections to that provider.
6. **Cross-month spanning** — confirmed bookings across three different months show up in the right `by_month` rows.
7. **Date validation** — `from > to` returns 400. Invalid format returns 422 (Pydantic validation). Range > 24 months returns 400.
8. **`confirmed_at` is set by `confirm_payment`** — a booking that goes through the confirm flow has a non-null `confirmed_at` close to "now". (Re-uses the existing confirm-path test infrastructure.)

Existing tests adjusted as needed:
- `tests/booking/test_confirm_path_snapshots_commission.py` — add an assertion that `confirmed_at` is set in addition to the commission columns.

Frontend changes are tested manually per the existing pattern. No browser automation in scope for this MVP.

## 9. Risks + open questions

- **`bill_generated_at` backfill is imperfect**: for bookings that went `pending → confirmed` skipping billing intent (an edge case the cash walk-in path used to allow), `bill_generated_at` may be NULL and we fall back to `created_at`. The fallback could over-attribute bookings to their lock month rather than their confirm month. For the current Neon deployment this affects only the seeded demo bookings — acceptable.
- **Decimal precision**: commission values are stored as `Float` (project convention). Sums of many rows can accumulate floating-point drift. Aggregations round to 2 decimals on output. Drift will be sub-cent on realistic volumes — acceptable for the demo. If precise accounting becomes important, migrate the column to `Numeric`.
- **No timezone handling**: `confirmed_at` is stored as naive UTC. Reports group on `confirmed_at` directly, so "June 2026" means "UTC June." Sudan is UTC+2, so a confirmation just after midnight local-time on July 1 lands in "June" UTC. Acceptable for the current scale.
- **Concurrent edits to rules during a period**: a rule changes mid-month → bookings confirmed before the change kept the old snapshot (immutable per the commission spec). Reports correctly sum the snapshotted amounts, not the current rate. No special handling needed.

## 10. Acceptance criteria

1. A fresh deploy gets the `confirmed_at` column added and historic confirmed bookings backfilled. Re-deploying does not re-execute the backfill (already-populated rows untouched).
2. Confirming a booking via `admin.service.confirm_payment` sets `confirmed_at` to the current UTC timestamp.
3. `GET /admin/reports` returns the documented shape, defaults to the last 6 months, accepts `from`/`to`/`provider_id` filters, and validates date format + range.
4. Financial sums exclude rows with `commission_amount IS NULL`. Operational counts include all confirmed rows.
5. Empty months appear in `by_month` arrays with zero values. Providers with no activity in the period do not appear in `by_provider`.
6. The admin Reports tab renders headline numbers, four tables (financial × 2, operational × 2), and four CSV download buttons. Filter changes refetch.
7. CSV downloads produce files matching the documented naming convention, contain the right rows, and open correctly in Excel and Google Sheets.
8. Both EN and AR translate every visible label, including in RTL mode.
9. On mobile (≤640px), tables collapse to stacked cards; the filter strip stacks to a single column.
10. The fifth tab appears in the admin home tab strip both on desktop and in the mobile fixed-bottom tab bar.
