# Provider Detail Page + Audit Log — Design Spec (Phase 1)

**Date:** 2026-07-23
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)
**Branch:** `feat/mobile-scaffold` (v2 frontend surface)
**Checkpoint tag:** `pre-provider-console-2026-07-23` on `8824f9d` — always-reachable revert point
**Related:** CLAUDE.md Deferred item "Audit log (A-MON-04)" — this ships the first half of it.
**Phase note:** This spec covers **Phase 1 only** — the audit log infrastructure + the admin-facing provider detail page. Phase 2 (operator-admin sub-role + creation UI + their scoped experience) gets a separate spec + plan cycle after Phase 1 ships.

## 1. Goal

Two connected changes on the admin console:

1. **Turn the Providers tab list into a click-through to a per-provider detail page.** Today, every provider row on the Admin → Providers tab renders inline capability toggles + block/unblock. That works for quick tweaks but is cluttered, and there's nowhere to surface deeper provider-level info. New pattern: rows become clickable, all the per-provider controls + a new activity log + a per-provider reports drilldown live on a dedicated `screen-admin-provider-detail` page.

2. **Introduce an audit log** (`audit_events` table + `record_event()` emit sites + `GET /admin/providers/{id}/log` endpoint) so admins can see what any given provider has been up to — trip creations, edits, deletions, capability changes, walk-ins, cash confirmations, consumer bookings on their trips, etc. Free-text keyword search + event-type filter + date range. This is the first concrete win the detail page delivers.

Phase 2 (deferred to a separate spec) will add a new **operator-admin** sub-role — a user account created by the admin that acts on behalf of a specific provider with all provider capabilities PLUS visibility into that provider's log + reports. The Phase 1 audit-log schema is designed to accommodate this without changes (`actor_user_id` already references any user; the operator-admin's user_id just plugs in there naturally).

## 2. Out of scope (Phase 1)

- **Operator-admin sub-role** — deferred to Phase 2.
- **Booking-expiration events from the Reaper** — `backend/src/booking/tasks.py` is marked "golden — do not modify" in CLAUDE.md. If the expire logic lives in a `booking.service` function the Reaper calls, we hook `record_event()` there. If it's inline in `tasks.py`, we skip and flag as a known gap.
- **Log CSV export** — reports get CSV export (already exists); the log itself is UI-only in Phase 1.
- **Log retention / archival** — the table grows unbounded. Not an issue at MVP volume; revisit if it grows past what Neon's free tier tolerates.
- **Historical event backfill** — the log starts empty on ship day. Previously-existing trip edits, walk-ins, capability toggles, etc. are not retroactively recorded. Empty-state UI copy documents the tracking-start date.
- **AR translation of `summary` strings** — `summary` is a pre-rendered English string baked in at emit time (see §4). All OTHER UI chrome on the detail page (section headers, filter labels, buttons, empty states, event-type labels used in the filter dropdown) gets full EN + AR i18n.
- **Multi-tenancy / provider hierarchy** (a provider having sub-providers) — not requested; would be a separate feature.
- **Log write access from anywhere other than the mutation service functions** — no admin "manually add a log entry" endpoint; the log strictly reflects real backend actions.

## 3. Architecture overview

```
                    ┌────────────────────────────────────────────┐
                    │  Admin → Providers tab (v2)                │
                    │  rows become clickable                     │
                    └───────────────┬────────────────────────────┘
                                    │  goto('admin-provider-detail')
                                    │  STATE.viewingProviderId = <id>
                                    ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  screen-admin-provider-detail                               │
        │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
        │  │ Access &     │  │ Activity log │  │ Reports          │   │
        │  │ permissions  │  │ (with filter │  │ (per-provider    │   │
        │  │ (existing +  │  │  strip)      │  │  drilldown)      │   │
        │  │  block btn)  │  └──────────────┘  └──────────────────┘   │
        │  └──────────────┘         │                  │              │
        └───────────────────────────┼──────────────────┼──────────────┘
                                    │                  │
                        GET /admin/providers/{id}/log  │
                                    │      GET /admin/providers/{id}/reports
                                    ▼                  ▼
        ┌───────────────────────────┐   ┌──────────────────────────┐
        │  audit.service.query_log  │   │  finance.reports         │
        │  (new)                    │   │  (existing, reused)      │
        └────────────▲──────────────┘   └──────────────────────────┘
                     │
             audit_events table
                     ▲
                     │  audit.service.record_event(...)
                     │  (called from every mutation site,
                     │   same-transaction as the caller)
                     │
        ┌────────────┴────────────────────────────────────────────┐
        │ Emit sites in existing service layers:                  │
        │   inventory/service.py (trip create/edit/delete)        │
        │   booking/service.py   (lock, walkin, provider-confirm) │
        │   admin/service.py     (approve, block, capabilities,   │
        │                         admin trip edit/delete,         │
        │                         payment confirm)                │
        └─────────────────────────────────────────────────────────┘
```

## 4. Data model

### 4.1 New table — `audit_events`

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    id             SERIAL PRIMARY KEY,
    actor_user_id  INT NOT NULL REFERENCES users(id),
    provider_id    INT NOT NULL REFERENCES users(id),
    event_type     VARCHAR(64) NOT NULL,
    target_type    VARCHAR(32) NULL,
    target_id      INT NULL,
    summary        TEXT NOT NULL,
    metadata       JSONB NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_events_provider_created
    ON audit_events(provider_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_events_provider_type_created
    ON audit_events(provider_id, event_type, created_at DESC);
```

### 4.2 Column semantics

- **`actor_user_id`**: the user who performed the action. Can be any role (admin, provider, or Phase-2 operator-admin). The FK is deliberately not scoped by role.
- **`provider_id`**: the provider whose log this event belongs to. Denormalized (rather than walking `target_id → trip → provider_id`) so the log survives deletion of the target row. When admin acts on provider P1's trip, `actor_user_id = admin.id, provider_id = P1.id`. When operator-admin acts for P1, `actor_user_id = op_admin.id, provider_id = P1.id`.
- **`event_type`**: kebab-case string. See §5 for the full enumeration.
- **`target_type` + `target_id`**: reference to what the action was ON (e.g. `('trip', 47)`, `('booking', 123)`, `('capability', null)`). Not foreign-keyed — targets may be deleted later; log must survive.
- **`summary`**: pre-rendered English one-line human string, safe to display directly. Baked in at emit time so log reads are O(1) (no joins). Examples: `"Alice (admin) edited trip #47: price 500→600"`, `"Bob (provider) added trip #99 (Cairo → Aswan, Oct 12 08:00)"`, `"Ahmed Hassan booked 2 seats on trip #47"`.
- **`metadata`**: JSONB for structured before/after diffs. Used later for rich rendering; not read by the Phase 1 UI. Example for a `trip_edited` event: `{"before": {"price": 500, "departure_time": "..."}, "after": {"price": 600, "departure_time": "..."}}`.
- **`created_at`**: server-side default `NOW()`.

### 4.3 Indexes

Two indexes carry all Phase 1 query patterns:
- `(provider_id, created_at DESC)` — the base "show me this provider's log newest-first" query
- `(provider_id, event_type, created_at DESC)` — filtered by event type

Free-text keyword search on `summary` uses `ILIKE '%q%'`. At MVP volume (thousands of rows per provider) this is fine without a `pg_trgm` index; if the table grows past ~100k rows per provider, add `CREATE INDEX ... USING gin (summary gin_trgm_ops)` in a follow-up.

## 5. Emit sites

New module `backend/src/audit/` with the shape:
```
audit/
  __init__.py
  models.py     # AuditEvent SQLAlchemy model
  service.py    # record_event(...), query_log(...)
  schemas.py    # Pydantic response schemas
  router.py     # (folded into admin/router.py or its own /admin/providers/{id}/log route)
```

### 5.1 `record_event()` signature

```python
def record_event(
    db: Session,
    *,
    actor_user_id: int,
    provider_id: int,
    event_type: str,
    summary: str,
    target_type: str | None = None,
    target_id: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Emit an audit event within the caller's active transaction.

    Does NOT commit — the caller's existing commit (or rollback) determines
    whether this event actually lands. This prevents 'logged an event for a
    mutation that got rolled back' races.

    Failures inside record_event() must NOT propagate — a bug in the audit
    layer must never break the actual mutation. Wrap in try/except; log the
    exception; return silently. Missing log entry > failed trip edit.
    """
```

### 5.2 Full emit-site enumeration

| Backend module + function | Event type | Actor | Notes |
|---|---|---|---|
| `inventory.service.create_trip` (called from `POST /trips`) | `trip_created` | provider | Called once per created trip (recurring pattern that creates N trips emits N events, each with its own trip_id). |
| `inventory.service.update_trip` (called from provider `PATCH /trips/{id}`) | `trip_edited` | provider | `metadata` carries `before` + `after` for `price` and/or `departure_time` (only fields that actually changed). |
| `inventory.service.delete_trip` (called from provider `DELETE /trips/{id}`) | `trip_deleted` | provider | `metadata` carries a snapshot of the trip at deletion. |
| Same functions called from `PATCH /admin/trips/{id}` + `DELETE /admin/trips/{id}` | `trip_edited` / `trip_deleted` | admin | Same event types, actor distinguishes. |
| `booking.service.lock_seats` (called from `POST /bookings/lock`) | `consumer_booked` | consumer | Summary includes customer's name (from `Passenger.full_name`) + seat count + trip route + date. |
| `booking.service.mint_billing_intent` (called from `POST /bookings/intent/billing`) | `billing_ref_generated` | consumer | Signals "customer committed to bank-transfer path." |
| `booking.service.lock_seats` (called from `POST /bookings/walkin`) | `walkin_booked` | provider | Same shape as consumer_booked but actor distinguishes. |
| `booking.service.provider_confirm` (called from `POST /bookings/{id}/provider-confirm`) | `cash_confirmed` | provider | |
| `admin.service.confirm_payment` (called from `POST /admin/payments/{id}/confirm`) | `payment_confirmed` | admin | Booking billing ref + amount in summary. |
| `admin.service.approve_provider` (called from `POST /admin/providers/{id}/approve`) | `provider_approved` | admin | |
| `admin.service.block_provider` / `unblock_provider` | `provider_blocked` / `provider_unblocked` | admin | Two distinct event types even if the endpoint is one toggle; helps UI icon distinction. |
| `admin.service.update_provider_capabilities` (called from `PATCH /admin/providers/{id}/capabilities`) | `capability_changed` | admin | `metadata` carries which flag(s) flipped and old→new values. |

### 5.3 Deliberate exclusion — booking expiration

The Reaper (`backend/src/booking/tasks.py`) releases expired locks and is CLAUDE.md-protected. During implementation:
- If the expire logic is implemented as a service-layer function (e.g. `booking.service.expire_lock`) that the Reaper calls, we hook `record_event()` there.
- If the expire logic is inline in `tasks.py`, we skip and add a note to CLAUDE.md's Known Limitations.

### 5.4 Same-transaction contract

Every `record_event()` call happens BEFORE the caller's `db.commit()`. If the caller's transaction rolls back (e.g. seat lock fails partway through), the audit row rolls back too. This is a hard correctness requirement.

Callers that already have a commit at the end (most service functions) get the audit row for free. Callers with unusual transaction boundaries (if any) need to be verified during implementation.

**Interaction with the "swallow exceptions" rule (§5.1):** if `db.add(audit_row)` raises inside `record_event()` and we simply `except Exception: pass`, the session may be left in an error state that breaks the caller's subsequent commit — silently defeating the "audit code never breaks the mutation" guarantee. The correct implementation uses a nested savepoint (`with db.begin_nested():`) inside `record_event()` so that a failed audit-row insert rolls back only the savepoint, leaving the outer transaction clean. Spelled out here so it doesn't get forgotten in the plan.

## 6. API endpoints

### 6.1 `GET /admin/providers/{provider_id}/log`

**Query params:**
- `q: str | None` — free-text keyword, matched with `ILIKE '%q%'` against `summary`.
- `event_type: str | None` — exact match on `event_type`.
- `from: str | None` — ISO date (`YYYY-MM-DD` or full timestamp), filters `created_at >= from`.
- `to: str | None` — same as `from`, filters `created_at <= to`.
- `limit: int = 100` — page size. Max 500.
- `before_id: int | None` — cursor for pagination. Returns rows with `id < before_id`, ordered `id DESC`.

**Response:**
```json
{
  "items": [
    {
      "id": 1234,
      "event_type": "trip_edited",
      "actor": {
        "id": 3,
        "full_name": "Alice",
        "role": "admin"
      },
      "target_type": "trip",
      "target_id": 47,
      "summary": "Alice (admin) edited trip #47: price 500→600",
      "metadata": {"before": {"price": 500}, "after": {"price": 600}},
      "created_at": "2026-07-23T12:34:56Z"
    }
  ],
  "next_before_id": 1123
}
```

`next_before_id` is `null` when there are no more pages. Client passes this back as `before_id` on the next request.

**Auth:** admin only in Phase 1. (Phase 2 widens to include operator-admin scoped to their `acts_for_provider_id`.)

**Status codes:** 200 on success; 404 if `provider_id` doesn't exist; 403 if non-admin.

### 6.2 `GET /admin/providers/{provider_id}/reports`

Thin wrapper around the existing `GET /admin/reports?provider_id={id}`:
- Same query params as `/admin/reports` (`from`, `to`) minus `provider_id` (inferred from URL path).
- Same response shape.
- Same aggregation logic reused verbatim from `finance/reports.py` — no new aggregation code.

Rationale for a separate endpoint: (a) cleaner URL from the provider-detail page's perspective, (b) becomes the natural place to widen the auth gate in Phase 2 (operator-admin scoped access).

**Auth:** admin only in Phase 1.

### 6.3 Existing endpoints unchanged

- `GET /admin/providers` — the list endpoint stays as-is; frontend just makes rows clickable.
- `PATCH /admin/providers/{id}/capabilities`, `POST /admin/providers/{id}/approve`, `POST /admin/providers/{id}/block` — all unchanged; the provider-detail page reuses them.

## 7. Frontend admin surface

**Constraint** (from CLAUDE.md, active on `feat/mobile-scaffold`): all v2 work lives in `frontend/index-v2.html`. `frontend/index.html` (v1) is a rollback surface and must not be touched.

### 7.1 Providers tab changes

- Rows become clickable (whole row, `cursor: pointer`).
- **Inline capability toggle chips + block button REMOVED** from each row.
- Rows now display: provider name · status pill · trailing `→` chevron.
- Click handler: `STATE.viewingProviderId = <id>` → `goto('admin-provider-detail')`.
- Trade-off acknowledged: admins lose ability to bulk-tweak capabilities from the list. Detail-page-per-provider was chosen deliberately — audit/oversight workflow value beats quick-toggle convenience.

### 7.2 New screen: `screen-admin-provider-detail`

Structure top-to-bottom (pillow design language throughout):

1. **Header** (compact strip): back arrow → returns to Providers tab · provider name (large) · status pill · email (secondary).
2. **Access & permissions** panel (pillow surface): reuses existing capability chip UI + block/unblock button; nothing new here structurally, just relocated.
3. **Activity log** panel (pillow surface, the primary content):
   - Filter strip: keyword input · event-type dropdown · date-from · date-to · Apply button (280ms debounce on keyword like existing filter strips).
   - Event rows: each row is a pillow-tinted line with an event-type icon (small colored dot), the pre-rendered `summary` text, an actor pill (name + role tag), and relative timestamp (`3m ago` / `Jul 20`).
   - "Load more" button at the bottom driving cursor pagination (passes `next_before_id` back).
   - Empty state pillow: "Activity log started 2026-07-XX. Actions before that date aren't recorded."
4. **Reports** panel (pillow surface, drilldown): the same Operational + Financial breakdown tables the top-level Reports tab shows, but scoped to this provider. Reuses existing table rendering from the Reports tab — no new table CSS. Export CSV button per table (same as top-level Reports).
5. **(Placeholder)** Operator-admin account panel: reserved for Phase 2, empty in Phase 1.

**Routing:**
- New STATE field: `STATE.viewingProviderId: int | null` (initialized `null`).
- Screen id: `screen-admin-provider-detail`.
- Registered in `PILLOW_SCREENS` set (learned from the recent Task 4 reset-flow work — otherwise the screen falls back to v1 styling).
- Registered in the CSS `body[data-screen="..."]` visibility chain at ~line 800.
- Hash-fragment navigation within page: `#permissions`, `#log`, `#reports` — on entry the page scrolls to the matching section if present.
- Back navigation uses existing history stack.

### 7.3 Reports tab changes

- Existing per-provider breakdown rows (from `financial_by_provider` / `operational_by_provider`) gain a trailing "View →" link.
- Link handler: same as clicking a Providers-tab row, plus scrolls to `#reports` on landing.
- Reports tab structure otherwise unchanged (aggregate view stays; per-provider drilldown is the new capability).

### 7.4 i18n

New EN + AR keys (~20 strings):
- Section headers: `admin.provider.detail.title`, `admin.provider.detail.permissions`, `admin.provider.detail.log`, `admin.provider.detail.reports`.
- Filter strip labels: `admin.provider.log.filter.keyword`, `admin.provider.log.filter.event_type`, `admin.provider.log.filter.date_from`, `admin.provider.log.filter.date_to`, `admin.provider.log.filter.apply`.
- Filter dropdown option labels for each `event_type` (11 event types × 2 languages = 22 strings, dropdown-only).
- Empty state: `admin.provider.log.empty`.
- Load more button: `admin.provider.log.load_more`.
- Back link: `admin.provider.detail.back`.
- Actor role tags (`admin`, `provider`, `consumer`): existing role-label keys reused.

`summary` strings are NOT translated — they render as-is (English) in both EN and AR modes. Documented in §2 as an explicit out-of-scope item.

### 7.5 Toast conventions carried forward

- All error-path `toast()` calls MUST pass `true` as the second arg (isErr flag). File-wide convention learned from the recent reset-flow work.
- All `api()` calls use `api(path, {method, body: JSON.stringify(...)})` signature.

## 8. Testing

### 8.1 Backend

- **`audit.service.record_event` unit tests** (~4 tests): inserts a row; participates in caller's transaction (rollback discards); silently swallows exceptions raised inside the function; correctly stores JSONB metadata.
- **Emit-site integration tests** (~11 tests, parametrized where possible): for each mutation endpoint, POST/PATCH/DELETE the endpoint via TestClient, then assert that a corresponding audit row landed with the right `event_type`, `actor_user_id`, `provider_id`, and non-empty summary.
- **Log query tests** (~5 tests): filter by `q`, `event_type`, `from`+`to`, cursor pagination boundary (`next_before_id` present/absent), and combined filters.
- **Auth tests** (~2 tests): non-admin role hits `/admin/providers/{id}/log` and gets 403; hits with invalid `provider_id` and gets 404.
- **Rollback-safety test** (~1 test): a mutation that fails mid-transaction (e.g. seat lock conflict) does NOT leave an audit row behind.
- **Estimated total: ~23 new tests** (140 → ~163).

### 8.2 Frontend

No automated frontend tests exist on this branch — verification is manual:
- Click through Admin → Providers → row → detail page appears with all four sections.
- Apply filters to the log; confirm rows update.
- Click "Load more"; confirm pagination.
- Click a per-provider row in Reports tab; confirm it lands on the detail page scrolled to `#reports`.
- Arabic RTL walkthrough on the new page.

## 9. Rollout + rollback

**Rollout:**
- `audit_events` table auto-created via existing lifespan `_ensure_schema()` + `_migrate_if_needed()` (`CREATE TABLE IF NOT EXISTS`). Zero manual migration steps on Render.
- Feature ships enabled by default; no feature flag. Additive change — no user workflow breaks.
- Post-deploy verification: perform a trip edit as a provider, then open the provider's detail page as admin and confirm the log row appears.

**Rollback:**
- **Code-level**: revert the merge. `audit_events` table is left in place (empty or holding whatever data landed) — dropping it is optional and unrelated to code state.
- **Data-level**: log data has no downstream consumers; safe to `DROP TABLE audit_events` if we ever want to fully undo.
- **Emit-site safety**: every `record_event()` call is wrapped in try/except (see §5.1) — a bug in audit code never breaks the actual mutation.

## 10. Deferred to Phase 2

Phase 2 will add, in a separate spec + plan cycle:

1. **New user role `operator_admin`** — new value in the users `role` enum + new nullable column `acts_for_provider_id INT FK users(id)`.
2. **Auth model widening**: existing provider auth guards (`Trip.provider_id == current_user.id`) resolve provider identity as `current_user.acts_for_provider_id if role == 'operator_admin' else current_user.id`. Operator-admin gets full provider capabilities (add/edit/delete trips subject to the provider's own capability flags, walk-in bookings, cash confirm, view manifests, view provider's bookings). PLUS: can view the activity log and operational/financial reports for their assigned provider (which primary providers cannot see today).
3. **Admin creation UI**: on the provider detail page, a new "Operator-admin account" section with a toggle. Admin fills in email + name; backend creates a `role='operator_admin'` user with `acts_for_provider_id = <this provider>`; admin sends temp password out-of-band OR the flow uses the newly-shipped `/auth/password-reset/*` endpoints for first-time password setup.
4. **Operator-admin frontend experience**: on login, `paintChrome()` routes them to the provider-home layout (they can add trips, walk in, etc.), plus two new tabs added just for their role: Log + Reports (both scoped to their `acts_for_provider_id`).
5. **Multiple operator-admins per provider**: Phase 2 defaults to 1:N (a provider can have several operator-admins, but each op-admin serves exactly one provider). Confirmed with user during brainstorming.
6. **API auth widening**: `/admin/providers/{id}/log` and `/admin/providers/{id}/reports` widen from admin-only to `admin OR operator_admin whose acts_for_provider_id matches`. No shape changes to the endpoints — just the auth gate.

Phase 1 is designed to accommodate all of this without schema changes — `audit_events.actor_user_id` already references any user, so operator-admin actions plug in naturally with `actor_user_id = op_admin.id, provider_id = <the provider they act for>`.

## 11. Open questions for the implementation plan

- **`admin.service.block_provider` vs. `unblock_provider`**: CLAUDE.md endpoint map lists only `POST /admin/providers/{id}/block`. Confirm during implementation whether it's a toggle (single endpoint) or two distinct endpoints. Either way, emit two distinct `event_type`s (`provider_blocked` / `provider_unblocked`) — helps UI icon differentiation.
- **Booking-expire event coverage**: check whether `booking.service` has an `expire_lock`-shaped function the Reaper calls. If yes, hook there. If not, skip and note in CLAUDE.md Known Limitations.
- **Actor name in `summary`**: emit-site code needs to look up `actor_user.full_name` and pass it into the summary template. If perf is a concern (extra query per mutation), pass the already-loaded `current_user` object down from the router; audit service accepts either an id or a user object.
- **Log-empty edge case for existing providers**: the empty-state UI copy needs a specific "started tracking" date. Pin it at implementation time to the actual ship date.

These get resolved in the implementation plan (writing-plans skill next).
