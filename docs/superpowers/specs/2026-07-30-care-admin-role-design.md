# Care Admin Role (Restricted RBAC Tier) — Design

**Status:** Design approved 2026-07-30. Ready for implementation-plan authoring.

**Goal:** Introduce a restricted admin tier — the "care admin" — intended for customer-care agents who handle client calls, look up trip / booking / operator context, and confirm pending payments. The tier is created and managed by full admins from the existing Settings hub. The design is deliberately minimally invasive: it adds one new role value (`care_admin`) on the already-string `User.role` column, one new auth dependency (`require_admin_or_care`), one new small router surface for lifecycle management, and role-driven UI hiding on the frontend. No schema migration is required for the primary role change.

**Non-goals:**
- Per-endpoint capability flags on admin accounts (the provider-side `can_*` pattern is not extended to admins in this spec).
- Multi-tenant / per-region scoping for care admins (all care admins see all bookings / trips / providers).
- Push-based logout when a care admin is blocked mid-session (the existing 403-on-next-request → sign-in bounce is sufficient).
- A separate care-admin sign-in portal (the existing single sign-in screen handles all roles).
- Email verification or admin approval for care-admin account creation (the creating admin vouches; account is active on creation).

---

## Perimeter

**Care admin CAN:**
- View the Providers list and the per-provider Detail page (Header + Activity Log panels).
- View all trips (list + detail).
- View all bookings (list + detail).
- View Pending Payments and **confirm** them (the one and only mutation care admin has).
- Manage their own Personal Information (rename, phone, national ID) via the role-neutral `PATCH /auth/me`.
- Reset their own password via the public `POST /auth/password-reset/{request,confirm}` flow.

**Care admin CANNOT:**
- Approve, block, or capability-toggle providers.
- Edit or delete trips.
- View the aggregate Reports tab or the per-provider Reports drilldown (financial rollups).
- Access the Commissions section in Settings (commission rate config).
- Manage other care admin accounts (only full admins do that).
- Anything customer or provider does — care admin is an admin-tier account.

---

## Architecture

### Role model

`User.role` is already a plain `Column(String, nullable=False, default="customer")`. Add `"care_admin"` as a fourth accepted value alongside `customer / provider / admin`. **Zero migration required** for the role column itself.

Care admins are always created with `status="active"` and `email_verified=True`. The full admin vouches for the account at creation time; no OTP / email-verification round-trip. If a full admin later wants to disable the account, they use the block flow (see below).

### Auth dependency

New dependency in `backend/src/auth/dependencies.py`:

```python
def require_admin_or_care(user: models.User = Depends(get_current_user)) -> models.User:
    """Accepts both `admin` and `care_admin`. Blocked accounts of either
    role are still rejected by `get_current_user`. Used on read-mostly
    admin endpoints plus the one care-admin mutation (payment confirm)."""
    if user.role not in ("admin", "care_admin") or user.status != "active":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
```

`require_admin` is left as-is (rejects `care_admin` with 403 — the intended behavior for every mutation-heavy admin endpoint).

### Router-level dependency change

Today, `backend/src/admin/router.py` sets `dependencies=[Depends(require_admin)]` at the router level. Per-endpoint dependencies **stack** — they do not override — so we cannot loosen the guard on a specific endpoint by adding `require_admin_or_care` beneath a router-level `require_admin`.

The router-level dependency is therefore **removed**. Every existing per-handler `admin=Depends(require_admin)` stays exactly as-is. Endpoints that today rely solely on the router-level guard get an explicit per-handler dependency added, matching whichever tier they belong to.

### Endpoint gating map

**Existing `/admin/*` endpoints:**

| Endpoint | Guard | Rationale |
|---|---|---|
| `GET /admin/providers` | `require_admin_or_care` | View — care admin needs the roster |
| `POST /admin/providers/{id}/approve` | `require_admin` | Provider lifecycle |
| `POST /admin/providers/{id}/block` | `require_admin` | Provider lifecycle |
| `PATCH /admin/providers/{id}/capabilities` | `require_admin` | Permission management |
| `GET /admin/providers/{id}/log` | `require_admin_or_care` | Per-provider audit log — supports customer-complaint troubleshooting; no financial aggregates (individual audit entries may reference per-transaction amounts, which is deliberate — care admin needs "when was payment X of SDG Y confirmed" to answer customer calls) |
| `GET /admin/providers/{id}/reports` | `require_admin` | Per-provider financial drilldown — same policy as aggregate Reports |
| `GET /admin/trips` | `require_admin_or_care` | View |
| `PATCH /admin/trips/{id}` | `require_admin` | Trip edit — full admin only |
| `DELETE /admin/trips/{id}` | `require_admin` | Trip delete — full admin only |
| `GET /admin/bookings` | `require_admin_or_care` | View |
| `GET /admin/payments/pending` | `require_admin_or_care` | View |
| `POST /admin/payments/{id}/confirm` | `require_admin_or_care` | **The single mutation care admin has** |
| `GET /admin/reports` | `require_admin` | Aggregate financials |

**New `/admin/care-admins` endpoints (all `require_admin`):**

| Endpoint | Purpose |
|---|---|
| `POST /admin/care-admins` | Create — body `{email, full_name, password}`. Uses `hash_password()`, sets `role="care_admin"`, `status="active"`, `email_verified=True`. Returns the new user summary. |
| `GET /admin/care-admins` | List all care-admin accounts (id, email, full_name, status, created_at). |
| `POST /admin/care-admins/{id}/block` | Sets `status="blocked"`. Existing `get_current_user` 403s blocked accounts on next request. |
| `POST /admin/care-admins/{id}/unblock` | Sets `status="active"`. |

Care admins are **not deletable**. Blocking preserves the `actor_user_id` foreign key on `audit_events` rows so the audit trail remains intact ("who confirmed payment X"). If a former care admin needs to be permanently disabled, block is the terminal state.

**Untouched (role-neutral or out-of-scope):**

- `PATCH /auth/me` (personal info) — role-neutral, care admin uses as-is.
- `POST /auth/password-reset/{request,confirm}` — role-neutral.
- `/notifications/*` — role-neutral.
- `/admin/commissions/*` — stays `require_admin` (matches "no Commissions in Settings").
- `/reports/mine` — provider-only (`require_active_provider`), care admin fails the role check naturally.

**Care admin API blast radius:** exactly one mutation — `POST /admin/payments/{id}/confirm`. Every other write is impossible via API, regardless of the frontend state.

---

## Care admin lifecycle

**Creation:** Full admin submits `POST /admin/care-admins` with `{email, full_name, password}`. The service creates the row with `role="care_admin"`, `status="active"`, `email_verified=True`. If the email already exists (any role), returns 409 with a clear message. The password is hashed with the existing `hash_password()` and stored in `password_hash` — no plaintext side channel.

**Communication:** Password is shown once in the create-modal response and communicated by the full admin to the care agent out of band (verbal, secure channel — same pattern already used for the seeded demo passwords). The care admin can change it after first login via the public forgot-password flow (`POST /auth/password-reset/request` → OTP → `POST /auth/password-reset/confirm`).

**Block:** Full admin clicks Block on a care-admin row. Row's `status` flips to `"blocked"`. On the blocked account's next authenticated request, `get_current_user` raises 403; the frontend's `api()` helper already routes 403s to sign-in.

**Unblock:** Reverse of block. `status` flips back to `"active"`.

**No deletion:** by design, per audit-trail preservation above. Block is terminal.

**Audit:** The existing `record_event()` seam already captures `actor_user_id` on payment confirmations. Care-admin confirms therefore attribute correctly with zero new instrumentation. The four care-admin lifecycle endpoints (`create`, `block`, `unblock`, `list`) also emit `record_event()` calls — `care_admin_created`, `care_admin_blocked`, `care_admin_unblocked` — using the existing nested SAVEPOINT + swallowing-try/except pattern established in Phase 1. Payload for each event stores the affected care-admin id + email for later drilldown.

---

## Frontend

### Chrome (`paintChrome()`) branching

Care admins get the **same admin shell** — topbar, tab-bar container, gear icon, bell, sign-out chip, language toggle. The differences are entirely in *what fills the tab-bar and the Settings hub*, driven by `STATE.auth?.user?.role`.

`paintChrome()` sets `document.body.dataset.role = 'care_admin'` for CSS scoping, and `#role-tag` renders "Care Admin" (new i18n key `role.care_admin` — EN "Care Admin", AR "دعم العملاء"). The existing `.topbar.role-*` CSS pattern picks up the new value automatically.

### Frontend gating helpers

Two small helpers land alongside the existing `isAdmin()` / `isProvider()`-style utilities in `frontend/index.html`:

```javascript
const isFullAdmin = () => STATE.auth?.user?.role === 'admin';
const isCareAdmin = () => STATE.auth?.user?.role === 'care_admin';
```

Every render function that needs to hide a mutation button uses `isFullAdmin()`. Care admin's read-only surfaces don't need `isCareAdmin()` explicitly — they fall through when `isFullAdmin()` is false.

### Admin tab-bar for care admin

| Tab | Care admin |
|---|---|
| Providers | ✓ |
| Trips | ✓ |
| Bookings | ✓ |
| Payments | ✓ |
| Reports | ✗ hidden |

Implementation reuses the `.hidden` toggle pattern the provider tab-bar uses for the `can_view_reports`-gated Reports tab. If care admin somehow lands on the Reports tab (stale client, forged URL), the Reports fetch 403s and the panel shows the standard error toast; no crash.

### Per-surface hiding rules

- **Providers list:** rows render exactly as admin sees them (name, status, created date). Row click still opens Provider Detail.
- **Provider Detail page:**
  - Header + Activity Log panels: unchanged.
  - **Permissions section: hidden** (four cap chips + approve/block buttons).
  - **Per-provider Reports drilldown panel: hidden** (endpoint 403s anyway — hide UI to avoid a visible error).
- **Trip cards (Admin Trips tab):** Manifest button ✓. **Edit + Delete buttons hidden.**
- **Booking rows:** no mutation buttons exist today; unchanged.
- **Pending Payments rows:** **Confirm Payment button visible** — care admin's one power.

### Settings hub sections for care admin

| Section | Care admin |
|---|---|
| Language | ✓ |
| Personal Information | ✓ (role-neutral) |
| Commissions | ✗ hidden |
| Care Admin Accounts | ✗ hidden (they can't manage each other) |

Personal Information is the only meaningful Settings surface for care admin. Password changes happen via the public forgot-password flow.

### Admin UI for managing care admins

New "Care Admin Accounts" section in the Settings hub (gear icon), visible only when `isFullAdmin()`. Placed adjacent to Commissions. Structure:

- **Header:** section title + short lead ("Create limited-access admin accounts for customer care agents. They can view bookings, trips, providers, and confirm pending payments.").
- **List area:** pillow-row treatment matching the Providers tab. Each row: email · full name · created date · status pill (green "Active" / red "Blocked"). Inline row actions: **Block** (danger-tinted) OR **Unblock** (moss-green) depending on status.
- **Empty state:** "No care admin accounts yet."
- **"+ Add care admin" button** in the section header — amber pill, opens `#care-admin-create-modal`.

**Create modal:**
- Inputs: full name (min two words, matches GEN-1 register rule), email, password (min length matches existing register rule).
- Password field uses `type="password"` + `autocomplete="new-password"` to keep it out of the admin's own browser autofill.
- Client-side validation mirrors the server; on submit → `POST /admin/care-admins` → close modal → re-render list.

**Lifecycle-event notifications:** none in-app. Care admin doesn't need a "your account was created" toast (they were told out-of-band). If blocked mid-session, the next request 403s and `api()` bounces them to sign-in.

### i18n

New EN + AR keys, all under `settings.care_admin.*` plus one top-level `role.care_admin`. Approximate list (final wording finalized during implementation):

- `role.care_admin`
- `settings.care_admin.title`
- `settings.care_admin.lead`
- `settings.care_admin.add_cta`
- `settings.care_admin.status.active`
- `settings.care_admin.status.blocked`
- `settings.care_admin.action.block`
- `settings.care_admin.action.unblock`
- `settings.care_admin.empty`
- `settings.care_admin.modal.title`
- `settings.care_admin.modal.name`
- `settings.care_admin.modal.email`
- `settings.care_admin.modal.password`
- `settings.care_admin.modal.submit`
- `settings.care_admin.toast.created`
- `settings.care_admin.toast.blocked`
- `settings.care_admin.toast.unblocked`

~17 keys × 2 languages = ~34 new entries in the `I18N` table.

---

## Auth flow

Care admins use the **existing sign-in screen** — no separate portal. On successful login, `paintChrome()` reads `STATE.auth.user.role`, sets `body.dataset.role`, and paints the trimmed admin shell (four tabs, Settings sections gated to Language + Personal Information).

The Welcome-screen `?demo=1` credential hint does **not** expose care-admin credentials — the seed does not create a demo care-admin account. Full admins create them at runtime.

---

## Testing

**Backend:**

- `test_default_role_is_customer_not_care_admin` — assert `User(...)` without explicit role does not accidentally land on `care_admin`.
- `test_create_care_admin_persists_role_and_active_status` — happy path for `POST /admin/care-admins`.
- `test_create_care_admin_hashes_password` — assert `password_hash != password`; assert bcrypt-shaped hash.
- `test_create_care_admin_email_already_exists_409` — duplicate email (any role) returns 409.
- `test_create_care_admin_requires_admin_401_and_403` — auth-required and role-gated (customer / provider / other care admin all 403).
- `test_list_care_admins_only_returns_care_admins` — filters out `admin` / `customer` / `provider` rows.
- `test_block_care_admin_sets_status` + `test_unblock_care_admin_sets_status`.
- `test_block_care_admin_causes_next_request_403` — end-to-end: block, then use the blocked account's still-valid JWT → 403.
- `test_require_admin_or_care_accepts_admin`.
- `test_require_admin_or_care_accepts_care_admin`.
- `test_require_admin_or_care_rejects_customer_provider_none`.
- `test_care_admin_can_view_providers` — `GET /admin/providers` 200.
- `test_care_admin_can_view_trips` — `GET /admin/trips` 200.
- `test_care_admin_can_view_bookings` — `GET /admin/bookings` 200.
- `test_care_admin_can_view_pending_payments` — `GET /admin/payments/pending` 200.
- `test_care_admin_can_confirm_payment` — `POST /admin/payments/{id}/confirm` 200; audit event records care admin as `actor_user_id`.
- `test_care_admin_can_view_provider_log` — `GET /admin/providers/{id}/log` 200.
- `test_care_admin_cannot_approve_provider` — `POST /admin/providers/{id}/approve` 403.
- `test_care_admin_cannot_block_provider` — 403.
- `test_care_admin_cannot_toggle_capabilities` — `PATCH /admin/providers/{id}/capabilities` 403.
- `test_care_admin_cannot_edit_trip` — `PATCH /admin/trips/{id}` 403.
- `test_care_admin_cannot_delete_trip` — 403.
- `test_care_admin_cannot_view_aggregate_reports` — `GET /admin/reports` 403.
- `test_care_admin_cannot_view_provider_reports_drilldown` — `GET /admin/providers/{id}/reports` 403.
- `test_care_admin_cannot_create_another_care_admin` — `POST /admin/care-admins` 403.
- `test_care_admin_cannot_list_care_admins` — `GET /admin/care-admins` 403.
- `test_care_admin_cannot_touch_commissions` — every `/admin/commissions/*` endpoint 403 (parameterized).
- `test_care_admin_password_reset_end_to_end` — care admin can request + confirm a password reset via the public flow.

Baseline is 191 tests (after the provider Reports ship). Expect ~+25 tests → ~216.

**Frontend:** manual smoke sequence in the plan (create, sign in, verify hidden UI, confirm payment, block, verify 403 bounce). No new automated frontend tests (the codebase does not have any today).

---

## Deferred / knowingly carried

- **Push-based logout on block.** If a full admin blocks a care admin mid-session, the care admin sees exactly one 403 on their next request and gets bounced to sign-in. Adding a WebSocket or long-poll heartbeat for this alone is not worth the operational cost.
- **Care admin action history in the audit log.** Every care-admin-triggered payment confirmation attributes correctly via `actor_user_id` on the existing `audit_events` table. A dedicated "Care Admin Activity" UI panel (per-agent activity feed) is possible in a follow-up but not shipped in scope. The data is already there for future querying.
- **Per-region / per-provider scoping.** All care admins today see all bookings / trips / providers. If a future requirement calls for regional or per-operator restriction (e.g. "SudanBus's care agent only sees SudanBus tickets"), that's a Phase-2 sub-scope layer atop this design — likely via a nullable `care_admin_scope` JSON column, similar to the deferred Phase-2 operator-admin `acts_for_provider_id`.
- **Care admin cap flags.** Not shipping. If we later need three or more tiers, revisit and consider Approach B (admin `can_*` flags) at that time.
- **Notifications on care-admin lifecycle.** No in-app notification to the affected care admin on create / block / unblock. Communication happens out-of-band.
