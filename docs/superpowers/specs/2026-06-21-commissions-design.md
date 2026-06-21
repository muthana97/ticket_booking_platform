# Commission System — Design Spec

**Date:** 2026-06-21
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)

## 1. Goal

Introduce a three-tier commission system that lets the admin take a configurable share of every confirmed booking. The system replaces the deferred "Commission rules + campaigns (Part 3.4–3.5)" item in CLAUDE.md.

The admin can set:
1. A **global** default commission applied when no override is configured.
2. A **per-provider** override that beats the global default for any trip operated by that provider.
3. A **per-provider+route** override that beats the per-provider rate for trips on a specific route.
4. A **per-trip** override that beats everything else for a single trip.

Precedence (most specific first): `trip > provider+route > provider > global`.

**Channel rule:** Commission only applies to **consumer-channel bookings** (`Booking.channel == 'consumer'`). Walk-in bookings (`channel == 'walkin'`) are always 0% — the provider sold the seat at their own counter, the platform contributed nothing, so it takes nothing. This is a hard rule, not a configurable rate.

## 2. Out of scope

- Multi-currency. SDG only.
- Commission paid out to admin via a separate transfer system. (Recorded only; reconciliation is future work.)
- Operator-side dispute / approval flow on commission. Admin's decision is final for the MVP.
- Backfilling commission onto existing confirmed bookings. Past bookings keep `NULL` commission columns.
- "Campaigns" (time-windowed promotional rates), tiered/sliding scales, volume bonuses. All future work.
- Phone-OTP login, payments path A, cancellations, audit log — same deferral as today.

## 3. Data model

### 3.1 New table — `commission_rules`

```
id                INT PK
scope             STRING  -- 'global' | 'provider' | 'provider_route' | 'trip'
provider_id       INT FK users(id), NULLABLE
route_id          INT FK routes(id), NULLABLE
trip_id           INT FK trips(id), NULLABLE
rate_kind         STRING  -- 'percentage' | 'flat_per_seat'
rate_value        FLOAT
created_at        DATETIME
updated_at        DATETIME
```

**Field rules:**

| `scope` | `provider_id` | `route_id` | `trip_id` |
|---|---|---|---|
| `global` | NULL | NULL | NULL |
| `provider` | required | NULL | NULL |
| `provider_route` | required | required | NULL |
| `trip` | required (= `trip.provider_id`) | NULL | required |

**Constraints:**
- Unique on `(scope, provider_id, route_id, trip_id)`. A rule for a given target is upserted, not duplicated.
- At most one row with `scope='global'`. Enforced at the service layer via an upsert (`PUT /admin/commissions/global` updates if present, inserts otherwise).
- `rate_kind='percentage'` requires `0 < rate_value <= 100`.
- `rate_kind='flat_per_seat'` requires `rate_value > 0`.

### 3.2 Booking row additions

Four new nullable columns on `bookings`:

```
commission_amount        FLOAT NULLABLE  -- snapshotted SDG amount
commission_rate_kind     STRING NULLABLE -- snapshot of rule.rate_kind at confirmation
commission_rate_value    FLOAT NULLABLE  -- snapshot of rule.rate_value at confirmation
commission_rule_id       INT NULLABLE FK commission_rules(id)  -- which rule won (audit trail)
```

All four stay `NULL` until the booking transitions to `confirmed`. Past confirmed bookings (created before this feature ships) stay `NULL` forever — no backfill.

## 4. Resolution algorithm

Implemented in `backend/src/finance/service.py` as `resolve_rule(db, trip) -> CommissionRule | None`.

```python
def resolve_rule(db, trip):
    # most specific tier first; short-circuit on first hit
    queries = [
        (db.query(CommissionRule)
            .filter(CommissionRule.scope == 'trip',
                    CommissionRule.trip_id == trip.id)),
        (db.query(CommissionRule)
            .filter(CommissionRule.scope == 'provider_route',
                    CommissionRule.provider_id == trip.provider_id,
                    CommissionRule.route_id == trip.route_id)),
        (db.query(CommissionRule)
            .filter(CommissionRule.scope == 'provider',
                    CommissionRule.provider_id == trip.provider_id)),
        (db.query(CommissionRule)
            .filter(CommissionRule.scope == 'global')),
    ]
    for q in queries:
        rule = q.first()
        if rule:
            return rule
    return None
```

If no rule at any tier (including no global default) → commission is 0. Admin must explicitly set a global to start collecting.

## 5. Snapshot at confirmation

Implemented in `backend/src/finance/service.py` as `snapshot_commission(db, booking, trip)`. Called by both confirmation paths immediately **before** the commit that flips status to `confirmed`:

1. `confirm_payment()` in `booking/service.py` — admin's `POST /admin/payments/{id}/confirm`.
2. The provider-confirm path in `booking/router.py` — `POST /bookings/{id}/provider-confirm` (cash walk-in).

```python
def snapshot_commission(db, booking, trip):
    # Walk-in bookings are always 0% commission — the provider sold at
    # their own counter, the platform contributed nothing. Hard rule.
    if booking.channel == 'walkin':
        booking.commission_amount = 0.0
        return
    rule = resolve_rule(db, trip)
    if rule is None:
        booking.commission_amount = 0.0
        return
    seat_count = len(booking.seat_ids or [])
    if rule.rate_kind == 'percentage':
        amount = round(booking.total_price * (rule.rate_value / 100.0), 2)
    else:  # 'flat_per_seat'
        amount = round(rule.rate_value * seat_count, 2)
    booking.commission_amount      = amount
    booking.commission_rate_kind   = rule.rate_kind
    booking.commission_rate_value  = rule.rate_value
    booking.commission_rule_id     = rule.id
```

Walk-in snapshots populate only `commission_amount = 0.0`. The other three columns (`commission_rate_kind`, `commission_rate_value`, `commission_rule_id`) stay `NULL` — there's no rule to attribute it to.

Snapshot is **immutable** after confirmation. Later edits to the rule (or rule deletion) do not retroactively change historical bookings.

## 6. Backend endpoints

All under `/admin` (admin-only via existing `require_admin` dependency).

### 6.1 Read

```
GET /admin/commissions
→ 200 {
    "global": { "rate_kind": ..., "rate_value": ..., "updated_at": ... } | null,
    "overrides": [
      {
        "id": int,
        "scope": "provider" | "provider_route" | "trip",
        "provider_id": int,
        "provider_name": str,
        "route_id": int | null,
        "route_label": str | null,        -- e.g., "Khartoum → Port Sudan"
        "trip_id": int | null,
        "trip_label": str | null,         -- e.g., "Trip #42 · 2026-06-25 14:00"
        "rate_kind": str,
        "rate_value": float,
        "updated_at": str
      }, ...
    ]
  }
```

Server-side decoration (`provider_name`, `route_label`, `trip_label`) keeps the frontend dumb. Sorted by specificity descending: trips → provider_route → provider.

### 6.2 Global default upsert

```
PUT /admin/commissions/global
body: { "rate_kind": "percentage" | "flat_per_seat", "rate_value": float }
→ 200 { ...the rule... }
```

Updates the singleton row if present; inserts if not. Validation per §3.1.

### 6.3 Override CRUD

```
POST   /admin/commissions/overrides
body: { "scope": "provider" | "provider_route" | "trip",
        "provider_id": int,
        "route_id": int (when scope == 'provider_route'),
        "trip_id":  int (when scope == 'trip'),
        "rate_kind": ..., "rate_value": ... }
→ 201 { ...the rule, decorated... }
→ 409 if a rule for that exact target already exists ("edit it instead")

PATCH  /admin/commissions/overrides/{id}
body: { "rate_kind": ..., "rate_value": ... }
→ 200 { ...the rule, decorated... }

DELETE /admin/commissions/overrides/{id}
→ 204
```

Validation:
- `scope='trip'` rules verify that `trip.provider_id == provider_id` (no cross-provider trip overrides).
- `scope='provider_route'` does not pre-check that the provider has trips on that route — admin may want to set the rate before adding trips.

### 6.4 Provider booking visibility

The existing `GET /bookings/provider/mine` response schema gains two fields per item:

```
commission_amount  float | null  -- null when not yet confirmed
net_amount         float | null  -- total_price - commission_amount when confirmed
```

No new endpoints. No new query. Just additional columns hydrated from the booking row.

## 7. Frontend UI

### 7.1 Topbar — gear icon

Admin-only icon between the language toggle and the session block in `frontend/index.html`. Click → `goto('admin-settings')`. Receives the same Capacitor haptics-on-tap as every other button.

```html
<button class="gear-btn" id="settings-btn" data-i18n-aria="settings.label" hidden>⚙</button>
```

Visibility is gated in `paintChrome()`: `gearBtn.hidden = STATE.auth?.user?.role !== 'admin'`.

### 7.2 Admin settings screen (`#screen-admin-settings`)

Section-list layout. Single column on mobile, capped at 760px on desktop. Each section is a `<section class="settings-section">` with a header and body. Forward-compatible — future sections (Account / password reset, etc.) are appended as additional `<section>` elements.

Phase 1 ships **one** section: Commissions. Account/password reset is a placeholder section (header only, body disabled) so the user can see where future work will land.

### 7.3 Commissions section content

**Global Commission card** at the top:
- Radio toggle: `Percentage` / `Flat per seat`
- Numeric input (suffix `%` or `SDG`)
- Save button → `PUT /admin/commissions/global`
- Empty state: "No global commission set — bookings carry zero commission until you set one."

**Overrides list** below:
- Header with `[+ Add override]` button
- Each row:
  - Scope badge (`PROVIDER`, `PROVIDER + ROUTE`, `TRIP`)
  - Human label (`Nile Coach Co.` / `Nile Coach Co. · Khartoum → Port Sudan` / `Trip #42 · 2026-06-25 14:00`)
  - Rate display (`8%` or `SDG 150 / seat`)
  - Edit / Delete icons
- Sorted by specificity descending (trips → provider_route → provider)
- Empty state: "No overrides yet."

**Add / Edit Override modal** — reuses the existing `.modal-bg` / `.modal-card` pattern from the Add Trip flow:
- Scope selector: three pills (Provider / Provider + Route / Trip)
- Conditional fields:
  - All scopes: provider `<select>`
  - `provider_route`: also a route `<select>` showing **all routes in the system** (not filtered to that provider's existing trips — the backend allows pre-setting a rate before trips exist; §6.3)
  - `trip`: also a trip `<select>` filtered to that provider's upcoming trips (you cannot rate-override a trip that doesn't exist yet)
- Rate kind radio + rate value input
- Cancel / Save
- 409 on submit → toast "Override already exists — edit it from the list."

### 7.4 Provider Bookings tab — visibility

Existing `provider-home` → `Bookings` tab gains two columns per row:

- `Commission` — shows `—` until confirmed; otherwise:
  - Consumer row with a rule: `SDG X` + small subtitle (`8%` or `SDG 150/seat`)
  - Consumer row with no rule: `SDG 0` (no subtitle)
  - Walk-in row: `SDG 0` + small subtitle `walk-in` (translated) so the provider knows why it's free
- `Net to you` — `—` until confirmed; otherwise `SDG (total - commission)` (equals `total_price` for walk-ins)

A new **footer summary band** appears above the table's bottom edge (mobile: stacked below the list):

```
Gross: SDG X · Commission: SDG Y · Net: SDG Z
```

Totals respect the active filter (the `q` / `origin` / `destination` / `status` strip). Footer values are computed client-side from the already-fetched rows; no extra request.

On mobile (< 640px), the Commission column collapses into the booking-detail expanded row to keep the table scannable.

### 7.5 i18n

~35 new keys split across:
- `settings.*` — screen title, section headers, breadcrumb, gear-icon aria-label
- `commission.*` — global form labels, override list, scope badges, rate-kind labels, validation toasts
- `commission.modal.*` — Add/Edit modal title, conditional field labels
- `provider.commission.*` — column headers, footer summary template

Both EN and AR. Arabic numerals stay en-US for receipt clarity per the existing pattern (`fmtMoney` is unchanged). Status badges (`PROVIDER` etc.) use the existing capitalisation rules. Crumb for the settings sub-screen translated.

## 8. Migration / deploy

The repo uses `Base.metadata.create_all()` at lifespan startup, plus a small `_migrate_if_needed()` step that runs idempotent `ALTER TABLE` statements for new columns on existing tables. The commission feature ships with:

1. **`commission_rules` table** — created by `create_all()` automatically once the model is registered.
2. **Booking column additions** — added by `_migrate_if_needed()` via four `ALTER TABLE bookings ADD COLUMN IF NOT EXISTS ...` statements (Postgres 15+; the repo already targets Render free-tier Postgres 15).

No data backfill. Existing confirmed bookings keep `NULL` commission columns.

## 9. Testing strategy

Unit tests in `backend/tests/finance/`:

1. `test_resolve_rule.py` — precedence matrix: with all four tiers populated, the right rule wins; with only some tiers, the next-most-specific wins; with no tiers, returns None.
2. `test_snapshot.py` — `snapshot_commission` with each `rate_kind`, including the rounding cases at 2 decimals; with `seat_ids = []`; with `total_price = 0`.
3. `test_admin_commissions_api.py` — endpoint smoke: PUT global upserts, POST override creates, POST duplicate returns 409, PATCH/DELETE work, non-admin gets 403.
4. `test_provider_booking_visibility.py` — `/bookings/provider/mine` exposes `commission_amount` and `net_amount` only on confirmed rows.

Integration smoke in `backend/tests/booking/`:

5. `test_confirm_path_snapshots_commission.py` — both confirmation paths (admin `confirm_payment` and provider cash-confirm) set the snapshot columns; walk-in confirmations short-circuit to `commission_amount = 0` with the other three snapshot columns left `NULL`, even when a matching rule exists.

Frontend changes are tested manually on mobile + web per `mobile/README.md` after backend is green.

## 10. Risk + open questions

- **Rounding policy.** Spec rounds to 2 decimals on snapshot. SDG is whole-currency in practice, but `total_price` is `Float` today so we keep fractional. Open to changing to integer SDG later as a separate cleanup.
- **Concurrent edits.** Two admin sessions editing the same global rule race — last write wins. Acceptable for MVP (single admin in practice).
- **Rule deletion while pending bookings exist.** Deleting a rule does not affect pending bookings, because snapshotting happens at confirmation. If the rule is deleted between booking creation and confirmation, the resolver falls through to the next tier (or to 0 if nothing remains). This is the documented behavior.
- **Provider-visible commission as a trust mechanism.** Per the user, commission is public to the provider. If the admin sets a punitive rate, the provider sees it. By design.

## 11. Acceptance criteria

- Admin can set a global commission, see it persist across reloads, and edit it.
- Admin can add an override at any of the three tiers; precedence resolves correctly when a booking is confirmed.
- A booking confirmed without any rule set has `commission_amount = 0` and `commission_rule_id = NULL`.
- A consumer-channel booking confirmed with a rule set has all four commission columns populated and they never change afterward.
- A walk-in booking always confirms with `commission_amount = 0`, regardless of any matching rule.
- Provider sees `commission_amount` and `net_amount` on every confirmed row of their bookings list, plus a totals footer.
- The Settings screen is reachable from a gear icon in the topbar; non-admin sessions do not see the gear.
- Both EN and AR render every label, including in RTL mode.
- Past confirmed bookings keep `NULL` commission columns; the feature does not retroactively touch history.
