# MVP Technical Scope & Guardrails (Claude Code Context)

## 🎯 What this build is
A web-portal MVP that demonstrates every role in `Context/requirements.v2.md`, **minus payments (PAY-04 / SYS-01) and cancellations (CAN-01..03)**. Currently deployed to Render's free tier for stakeholder testing; upgrade to paid when sign-off comes.

Auth is currently **email + password for all roles** (deferred realignment to phone-OTP for customer/provider per AUTH-01 / P-AUTH-01).

## 🎨 Redesign in progress — "Pillow" (v2)

Active full visual makeover from the current paper/terra editorial style to the **pillow** design language (soft pastel gradient · near-white 3D-pillow cards · amber `#F4A81D` pill CTAs · faint diagonal-line screen texture · tabular Inter numerics). Direction picked 2026-07-17 from `demos/demo-7.html` (mobile) + `demos/demo-7-desktop.html` (desktop customer phone-column + admin dashboard shell). Accent color moved from the demo's midnight navy to amber during the welcome/sign-in build — reads warmer and gives the pastel surface more energy without losing the pillow's calm.

### Preservation setup (in place)
- **Branch**: `redesign/pillow` off `feat/mobile-scaffold`. All v2 work lives here. `main` + `feat/mobile-scaffold` stay pristine until sign-off.
- **Tag**: `pre-redesign-2026-07-17` on `eb08561` — always-reachable revert point.
- **Side-by-side file**: `frontend/index-v2.html` starts as a byte-for-byte copy of `frontend/index.html` (created 2026-07-17 on `dfee59d`). `index.html` is **never** touched during the redesign — every migrated screen lands in `index-v2.html` only.
- **Backend switch** (`backend/src/main.py` `_serve_ui`): explicit `GET /app/` and `GET /app` routes register BEFORE the static mount. They read `?ui=` query param + `taz_ui` cookie:
  - `?ui=v2` → serves `index-v2.html` + sets year-long cookie (path `/app/`, SameSite=Lax)
  - `?ui=v1` → serves `index.html` + sets cookie (cancels opt-in)
  - cookie alone → whichever the cookie says
  - neither → v1 (default)

  Query param always beats cookie so users can flip via URL. Response is `Cache-Control: no-cache` so v2 iterations show up on refresh. `/app/vendor/*`, `/app/sw.js`, `/app/manifest.json` still served by the static mount unchanged. Smoke-tested end-to-end with `TestClient`.

### Rollback
- **User-level**: hand out `?ui=v1` (removes cookie); the default is v1 the whole time so no server change is needed.
- **Full**: `git checkout pre-redesign-2026-07-17` — reachable via tag.
- **Data**: redesign is frontend-only. Neon DB + backend untouched. Worst case a UI bug prevents booking on v2; v1 stays reachable.

### Pillow design system (v2 tokens)
Palette:
```
--bg-a: #E8F0FF   soft blue  --bg-b: #E9F5EC   soft mint
--card: #FBFCFF   near-white pillow  --card-tint: #F1F5FC  secondary pillow
--ink: #0F1526    --ink-mute: #5B6478   --ink-faint: #98A0B3
--accent: #F4A81D amber           --accent-on: #1A1000
--ok: #17A66B     --warn: #E39A2A       --danger: #D94A3E
--shadow-drop: rgba(50,80,140,0.10)     --shadow-tight: rgba(50,80,140,0.04)
--hi-line: rgba(255,255,255,0.85)       top-highlight inset on pillows
```
Screen texture: `repeating-linear-gradient(-45deg, transparent 0 13px, rgba(15,21,38,0.055) 13px 14px)` layered over the pastel gradient — faint diagonal lines.

Font: **Inter** (400/500/600/700/800), `font-variant-numeric: tabular-nums` on all numerics.

Primitives (see `demos/demo-7.html` for reference impls):
- `.pillow` — near-white card, 22px radius, dual-shadow (soft drop + top-highlight-inset) to fake 3D depth.
- `.cta` — full-width 999px pill, amber fill, drop shadow tinted `rgba(180,110,10,0.45)`.
- `.status-pill` — small dark rounded pill (nods to the reference currency-app's "1USD = 7.2493 CNY" chip).
- `.chip` — rounded chip with tinted circular icon dot (city pickers).
- `.swap-btn` — 44px dark circle between origin/destination pillow cards.
- `.seat` / `.sel` / `.booked` — pillow-tile seat treatment.
- Ticket: pillow surface with `::after` dashed perforation line.

### Migration order (screens)
Style-only rewrites where possible — keep all JS logic (`goto()` state machine, API layer, i18n, RTL, `tazStore`, `tazShare`, long-poll) byte-for-byte. Change HTML markup + `<style>` block only. All new screens/copy get EN + AR i18n keys added to the `I18N` table.

**Customer** (passenger cycle fully migrated — 2026-07-18):
- [x] Welcome + sign-in
- [x] **NEW screen — category chooser**: sits between login and search. Two large tiles — a filled bus icon and the word "Other" — no h2/lead so the tiles fill the screen; topbar-nav hidden here so the chooser is a real commit point.
- [x] **NEW screen — Others coming-soon** with back button (via subhead + history pop).
- [x] Search trips + **bottom nav** (Search · My Tickets · Support). Two stacked chip cards with a 46px dark swap button punched through the middle; frosted pastel bottom bar on mobile with amber active state.
- [x] Trip detail / booking (seat map + panels). Pillow-tile seats (near-white/amber/muted/danger for available/selected/locked/booked), each right-column panel is its own pillow surface, dark ink countdown with tabular numerics.
- [x] My Tickets (list + past). Three sections with left-edge accent stripes (warn/ok/muted), booking rows as pillow surfaces, View ticket → amber pill on Awaiting, ghost outline on Upcoming/Past.
- [x] Ticket modal (PAID/PENDING/EXPIRED status bar preserved and mapped to `--p-ok` / `--p-warn` / `--p-danger`). Near-white pillow ticket over dark navy backdrop; perforation notches retinted; billing ref amber-outlined; amber Print CTA.

**Provider**:
- [ ] Provider home (My Trips + My Bookings tabs).
- [ ] **Filter strips — `From` / `To` inline with dropdown boxes** (currently on a separate row above; asked to reclaim vertical space).
- [ ] Add-trip modal.
- [ ] Trip-edit modal.
- [ ] Manifest modal + CSV export.

**Admin**:
- [ ] Admin home (Providers / Trips / Bookings / Payments / Reports tabs).
- [ ] Filter strips — same `From`/`To` inline-label fix as provider.
- [ ] Admin Settings hub (Commissions + Account).

**Cross-cutting**:
- [ ] Notifications screen.
- [ ] Arabic RTL pass on all v2 screens (existing polish backlog still applies: `.tab-support` font-size normalization, `→` glyph flip in RTL routes).
- [ ] Native (Capacitor) — decide when to point mobile at v2. Currently `webDir: ../frontend` loads `index.html`; will keep loading v1 until we rename or repoint at `index-v2.html`.

### Constraints carried into v2
1. **Style-only** — keep JS/i18n/API/state byte-for-byte. Only HTML markup + CSS block change.
2. **i18n coverage** — every new visible string gets EN + AR keys in `I18N`. Placeholders use `data-i18n-placeholder`. Numeric elements force LTR direction in RTL mode (see `frontend/index.html` for the pattern).
3. **Ticket status bar** — PAID / PENDING / EXPIRED coloring is a hard requirement. Translate colors to pillow tokens.
4. **Bottom nav** — customer-only on v2 mobile view. Provider + admin keep their tab-bar treatment (adapted to pillow style, but not converted to a bottom nav).
5. **No `frontend/index.html` edits** on this branch. If a bugfix is genuinely needed in v1, land it on `feat/mobile-scaffold` and merge that branch into `redesign/pillow`.

## 👥 Roles & data isolation (live)
| Role | Status model | Access |
|---|---|---|
| Customer | `active` after email verification | Search trips · book seats · view own tickets |
| Provider | `pending` → admin approves → `active` (or `blocked`) · per-provider capability flags (`can_add_trips`, `can_edit_trips`, `can_delete_trips`) default TRUE | Manage own trips (add/edit/delete subject to flags) · walk-in bookings on own trips · view own bookings · view own trip manifests |
| Admin | seeded `active` only (or env-overridden, see below) | Approve/block providers · toggle per-provider capabilities · view/edit/delete all trips · view all manifests · search all bookings · confirm pending payments |

**Provider data isolation is enforced server-side** — `Trip.provider_id` checked on `PATCH /trips/{id}`, `DELETE /trips/{id}`, `POST /bookings/walkin`, and `GET /bookings/trips/{id}/manifest`. A provider cannot see or touch another provider's trips/bookings/manifests. Trip rows in customer + admin views display the operating provider's name via `inventory.service.decorate_trip_row()`. The ticket payload also carries `trip.provider_name` so every ticket clearly shows the operator.

## 🗺️ Endpoint map
**Auth:** `POST /auth/register` · `POST /auth/verify-email` · `POST /auth/resend-otp` · `POST /auth/login` · `GET /auth/me`

**Trips:** `GET /trips/search` (open) · `GET /trips/mine` (active provider, own trips only — accepts `q` / `origin` / `destination` / `time`) · `POST /trips` (active provider, gated on `can_add_trips`; accepts a `repeat` pattern + `days_of_week` + `end_date`; returns `TripsCreatedResponse`) · `PATCH /trips/{id}` (active provider, own only, gated on `can_edit_trips`; partial `price` + `departure_time` — past-departure blocked; emits notifications) · `DELETE /trips/{id}` (active provider, own only, gated on `can_delete_trips`; emits notifications)

**Bookings:**
- `POST /bookings/lock` (consumer) · `POST /bookings/walkin` (provider, on own trips only)
- Both flow through `lock_seats()` which enforces the passenger-name rules (GEN-1): each `full_name` must contain ≥ 2 words; no dupes inside one booking; no dupes across active bookings on the same trip. Phone + national ID are optional per passenger.
- `POST /bookings/intent/billing` (Path B billing reference) · `POST /bookings/{id}/provider-confirm` (active provider on their own trip — one-shot cash confirm for walk-ins; P-PAY-03)
- `GET /bookings/{id}/ticket` (re-fetch ticket payload, no state mutation)
- `GET /bookings/me` (customer's own consumer bookings)
- `GET /bookings/provider/mine` (active provider's bookings, both channels — accepts `q` / `origin` / `destination` / `status`)
- `GET /bookings/trips/{id}/seats/stream` (long-polling, version-stamped)
- `GET /bookings/trips/{id}/manifest` — access-scoped: admin → any; owning provider → own; customer → 403.

**Admin:** `GET /admin/providers` · `POST /admin/providers/{id}/approve|block` · `PATCH /admin/providers/{id}/capabilities` (partial update of `can_add_trips` / `can_edit_trips` / `can_delete_trips`; emits `provider_capability_changed` to the affected provider) · `GET /admin/trips` (filterable by `q`, `origin`, `destination`, `time`, `provider_id`) · `PATCH /admin/trips/{id}` (any trip, bypasses ownership + capability; emits notifications) · `DELETE /admin/trips/{id}` (emits notifications) · `GET /admin/bookings` (filterable by `status`, `q`, `origin`, `destination`) · `GET /admin/payments/pending` · `POST /admin/payments/{id}/confirm` · `GET /admin/reports?from=&to=&provider_id=`

**Notifications:** `GET /notifications/me` (returns `{unread, items[]}`, latest 50 newest-first) · `POST /notifications/{id}/read` · `POST /notifications/read-all`. Emit sites: trip edit → passengers (if time changed) + counter-party; trip delete → passengers + owning provider (admin only); capability toggle → affected provider.

## ✂️ Deliberately deferred (V2)
- Path A direct payments (SYS-01) — admin manual `POST /admin/payments/{id}/confirm` is the MVP substitute.
- Cancellations + refunds (CAN-01..03).
- Commission **campaigns** (time-windowed promotional rates, Part 3.5). Base commission rules shipped 2026-06-21 — see Recent Fixes.
- Financial / operational reports (3.6–3.7).
- Phone-OTP login (AUTH-01, P-AUTH-01).
- Real SMS transport (SYS-02). Email transport IS wired (SMTP via env) — but blocked on Render free tier (see Known Limitations).
- Arabic RTL (NFR-15).
- Audit log (A-MON-04).
- Offline manifest cache (NFR-13).

## 🛠️ MVP Hard Requirements (still binding)
1. **Shared Locking Core** — `POST /bookings/lock` and `POST /bookings/walkin` both call `service.lock_seats(...)` atomic transaction.
2. **Fixed Fleet Seating** — only 45-seat (10×2x2 + 5-back) or 48-seat (3 front + 10×2x2 + 5-back). Enforced in `inventory.service.generate_seat_names`.
3. **Stakeholder Ticket Output** — `TicketResponse` carries booking, trip, passengers, seat map, `BOK-XXXX-XX` billing ref, `delivered_to` (when SMTP wired), and `qr_payload` (TKT-04 — frontend renders via qrcodejs).
4. **Real-time State Sync** — long-polling at sub-second latency on change.
5. **Provider data isolation** — server-side gate on cross-provider operations.
6. **Admin oversight** — provider approval, trip oversight, all-bookings search/filter, manual payment confirmation.
7. **Future-only departures + recurring schedules** — `POST /trips` accepts a `repeat` pattern (`once` / `daily` / `weekly` / `custom`) plus `end_date` and `days_of_week`. Past departures are rejected with 400. Capped at 60 trips / 90-day horizon per request.
8. **Provider cash confirmation** (P-PAY-03) — `POST /bookings/{id}/provider-confirm` lets an active provider one-shot cash-confirm a walk-in on their own trip: status `pending|committed_pending` → `confirmed`, `payment_method='cash'`, seats `locked` → `booked`. A billing reference + `bill_generated_at` is minted on confirmation if absent, so cash bookings still get a printable ticket + QR. Cross-provider attempts return 403. Surfaced two ways in the UI: inline **"Confirm Payment"** CTA on the post-lock booking panel **and** per-row button on the Provider Bookings tab. The provider walk-in flow deliberately does **not** expose "Generate Billing Reference" — a ref generated by the provider would only be settleable from the admin portal, which broke the flow.
9. **Email-OTP rate limit** (NFR-08 / ERR-04) — `_generate_email_otp` enforces 30-second cooldown between requests for the same email + max 3 codes per email per hour. Returns 429 with a human-readable detail. Frontend mirrors the cooldown via a live `Resend in 23s` countdown on the resend button.
10. **Passenger name rules** (GEN-1) — enforced inside `lock_seats()` before any seat lock is taken: each `full_name` must contain at least two whitespace-separated words; no two seats within a single booking may share a normalized (lowercased + whitespace-collapsed) name; no name may collide with an existing passenger on an active (`pending` / `committed_pending` / `confirmed`) booking for the same trip. Rejects with 400 and an actionable message ("Add an additional name (e.g. a middle or family name) to differentiate."). Frontend mirrors rules 1 + 2 for a faster fail; rule 3 stays server-only.
11. **Trip edit** (Task #4) — `PATCH /trips/{id}` and `PATCH /admin/trips/{id}` partial-update `price` and/or `departure_time`. Price changes affect **new bookings only**; existing bookings keep their locked `total_price`. Backend refuses departures that would move fully into the past. Provider path is gated on ownership + `can_edit_trips`; admin path bypasses both. Every edit fans notifications: time change → passengers, edit itself → counter-party (provider ↔ admin).
12. **Admin capability toggles** (ADMIN-2) — three `Boolean NOT NULL DEFAULT TRUE` columns on `users` (`can_add_trips`, `can_edit_trips`, `can_delete_trips`) gate `POST /trips`, `PATCH /trips/{id}`, `DELETE /trips/{id}` for the specific provider. Admin bypasses all three via the `/admin/trips/*` routes. Toggled from the Admin Providers tab (checkbox row visible only for active providers); every real flip emits a `provider_capability_changed` notification.
13. **Notifications subsystem** (Task #5) — `notifications` table (user_id, type, JSON payload, created_at, nullable read_at). Bell icon in the topbar session block for every logged-in role, unread count refreshed on every `paintChrome()`. Universal `/screen-notifications` renders per-type icon + title + sub + relative timestamp; click marks read (server + client) and best-effort routes to the relevant surface. Event catalog: `trip_time_changed`, `trip_edited_by_provider`, `trip_edited_by_admin`, `trip_cancelled`, `trip_deleted_by_admin`, `provider_capability_changed`.
14. **Ticket status bar** — the single top strip on the ticket modal is colored + labeled by the booking's live state: green **"PAID"** for confirmed, amber **"PENDING PAYMENT"** for pending / committed_pending, red **"EXPIRED TICKET"** when explicitly expired OR the trip's departure is already in the past. Same coloring survives the print stylesheet (perforated edges suppressed on print).

## 🌐 Localization (EN / Arabic)
- Topbar carries an `EN / عربي` toggle (Fraunces 14px, prominent border). Choice persists in `localStorage` (`taz.lang`).
- Translation runtime: a 130+ key `I18N` table + `applyLanguage()` walks every `[data-i18n]` element and swaps `textContent`. `data-i18n-html="1"` opts the element into `innerHTML` (for strings with embedded links). `data-i18n-placeholder` covers input placeholders.
- Helpers: `t(key)`, `tStatus(s)` and `tChannel(s)` for backend-supplied enum strings (e.g. `status.pending`, `channel.walkin`).
- Arabic mode flips `<html dir="rtl">`, swaps display font to **Amiri** (Google Fonts), and forces LTR direction on numeric / mono elements (seat map, prices, billing refs, codes). Dates render in Arabic locale (Arabic month names + Arabic-Indic numerals); money stays en-US digits for receipt clarity.
- Coverage: welcome, sign-in, register (incl. password confirm), verify-email, provider-pending, customer search + trip cards, booking screen (panels, legend, lock/walk-in CTAs, countdown, per-passenger name/phone/ID inputs with GEN-1 error messages), My Tickets sections + pills, provider home tabs + bookings + add-trip modal (incl. repeat picker, day-of-week chips, end-date), **trip-edit modal**, **manifest modal + CSV column headers**, admin console (4 tabs, both filter strips, all row actions, **per-provider capability toggles**), **notifications screen + per-type templates + relative time strings**, ticket modal (every field, stamps, status bar labels, delivered banner, "Operated by" line, buttons). Status + channel pills translate per-row.

## 🧪 Demo credentials (from `seed.py`)

**Admin** is overridable via env (`ADMIN_EMAIL` / `ADMIN_PASSWORD`). If unset, falls back to the committed defaults. Demo customer + providers stay hardcoded — they're throwaway demo data.

| Role | Email | Password |
|---|---|---|
| Admin (default) | `admin@tazkirati.app` | `TazAdmin#MVP-2026` |
| Customer | `passenger@tazkirati.app` | `Passenger#2026` |
| Provider — Nile Coach Co. | `operator@tazkirati.app` | `NileOps#2026` |
| Provider — SudanBus Express | `ops@sudanbus.app` | `SudanOps#2026` |

Two providers ship by default so data-isolation can be demoed end-to-end. Three sample bookings on the customer account: 1 committed_pending, 1 confirmed (upcoming), 1 confirmed (past — populates "My Tickets · Past").

⚠️ Welcome screen no longer displays credentials. Stakeholders can append `?demo=1` to the URL for a credential hint (emails only — passwords shared out-of-band).

## 🚀 Cloud deploy (Render web service + Neon Postgres)

The repo ships a `render.yaml` blueprint at the root. Dockerfile lives at repo root (`./Dockerfile`) so both Render's Blueprint flow and manual Web Service flow find it. **Postgres is hosted on Neon (free tier)** — we migrated off Render's managed Postgres on 2026-06-22 when the 90-day free-trial expiry suspended the original DB.

**Deploy from scratch:**
1. Provision a Postgres instance on [neon.tech](https://neon.tech) (free tier, 0.5 GB storage, no expiry). Copy the connection string — Neon hands it out as `postgresql://…` (already the form SQLAlchemy 2.x wants; the `postgres://` normalizer in `database.py` is now defensive only).
2. Connect this repo to Render.
3. Render dashboard → New + → **Web Service** → select repo → set **Branch** to `feat/mobile-scaffold` (or whatever working branch you're shipping). Render reads `render.yaml` for the service config.
4. In the web service Environment tab, set the `sync: false` env vars manually:
   - `DATABASE_URL` → paste the Neon connection string (the `databases:` block in `render.yaml` is no longer used; ignored harmlessly)
   - `CORS_ALLOWED_ORIGINS=<deployed-url>`
   - `ADMIN_EMAIL` + `ADMIN_PASSWORD` (optional — override the seed defaults)
   - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` (optional — see Known Limitations)
5. **Auto-seed**: on first boot, `_bootstrap_if_empty()` in `main.py` lifespan runs `seed.py` if no admin exists. Required because free tier has no Shell to run scripts manually. Idempotent across cold starts.

**Why Neon for the DB:**
- No 90-day expiry (unlike Render free Postgres).
- Generous free tier (0.5 GB / month), auto-scales to zero when idle (~1s cold start to wake the DB).
- Same wire protocol — no app code change. Schema rebuilds on first boot via `_ensure_schema()` + `_migrate_if_needed()` so a fresh Neon DB is zero-effort.
- Render web tier ($0 free) still does its 15-min sleep + 30s cold-start. The "Waking up the server…" toast in the frontend covers that visibly.

**Render-side facts to know:**
- Web service sleeps after 15 min idle (~30s cold-start).
- 1 worker only (which is *why* the Reaper-in-process pattern is safe).
- **Outbound SMTP is blocked on Render free tier** — see Known Limitations.

**Auto-deploy branch:** `render.yaml` has **no `branch:` directive** so Render defaults to whatever you set in the dashboard. Set it to your working branch (e.g. `feat/mobile-scaffold`) — otherwise Render silently deploys from `main` which may be behind your active work.

**Upgrade path (when stakeholders sign off):**
- Bump web service `plan: free` → `plan: starter` ($7/mo) in `render.yaml`.
- Bump uvicorn `--workers` in `Dockerfile` CMD.
- When workers > 1, **extract the Reaper** into a separate `worker` service so it doesn't multiply across uvicorn workers. Reaper code is self-contained in `backend/src/booking/tasks.py`.
- Update env: `DB_POOL_SIZE=10`, `DB_POOL_MAX_OVERFLOW=20`.
- Outbound SMTP unblocks on Render Starter.
- Neon: upgrade Launch plan ($19/mo) if you outgrow the free tier — adds branching, larger storage, point-in-time restore.

## ⚠️ Known production limitations

| Limitation | Impact | Workaround |
|---|---|---|
| Outbound SMTP blocked (port 25 / 587 / 465) on Render free tier | Email OTP `_send_email()` returns `[EMAIL] SMTP delivery failed: OSError(101, 'Network is unreachable')`. Falls back to `[EMAIL-OTP-CONSOLE]` log line. Users can't verify via email. | (a) Upgrade to Render Starter, or (b) switch from SMTP to an HTTP-API email service (Resend / SendGrid / Mailgun). Resend is the easiest swap. |
| No Shell tab on Render free tier | Can't run `python seed.py` manually. | Auto-seed on lifespan startup (already implemented). |
| Web service sleeps after 15 min | First request after sleep takes ~30s. | Acceptable for stakeholder demo; upgrade removes it. |
| Neon DB auto-suspends after ~5 min idle | First DB query after suspend adds ~1s wake latency. | Tolerable; transparent to users; Neon Launch plan disables suspend. |

## 📱 Mobile (iOS + Android via Capacitor)

Native apps are a Capacitor wrap of the existing `frontend/` SPA — same vanilla JS, same i18n/RTL, same long-poll. Scaffold lives in `/mobile/`.

**Layout:**
- `mobile/package.json` — Capacitor 6 core + `@capacitor/{ios,android,preferences,network,app,status-bar,splash-screen,assets}`.
- `mobile/capacitor.config.ts` — `appId: app.tazkirati`, `webDir: ../frontend` (so any web change flows in on next `npx cap sync`).
- `mobile/ios/` + `mobile/android/` — generated by `npx cap add <platform>`, committed.
- `mobile/README.md` — setup commands, smoke-test checklist, store-submission prereqs.

**Runtime contract (web ↔ native split, all in `frontend/index.html`):**
- `TAZ_API_NATIVE_DEFAULT` (single top-of-script constant) — backend URL used inside the Capacitor webview. **You must set this to your Render URL before building.** Web build ignores it and uses `location.origin`.
- `window.__TAZ_API__` — runtime override for staging swaps, takes precedence.
- `tazStore` — persists `STATE.auth` via `@capacitor/preferences` only on native. Web stays in-memory.
- `pauseStreamLoop()` / `resumeStreamLoop()` — wired to `Plugins.App.appStateChange`, halts the seat long-poll when backgrounded (battery + cellular).
- `Plugins.App.backButton` (Android only) — closes any open `.modal-bg.show` first, then pops in-app history via `back()`, finally calls `App.exitApp()` at root. iOS never emits this event so the listener is harmless there.
- Cold-start toast (`toast.waking_server`) — fires 2.5s into the first non-stream API call, once per session. Mitigates Render's 30s wake.
- Service worker registration skipped on native — redundant inside a webview.
- QR lib is bundled at `frontend/vendor/qrcode.min.js` (was a CDN dep) so the ticket QR renders on first launch / cellular.
- Backend CORS (`backend/src/config.py:cors_origins`) always appends `capacitor://localhost`, `https://localhost`, `http://localhost`, `ionic://localhost` to the strict allow-list, so no operator action needed for native origins.
- Viewport sizing uses `100dvh` not `100vh` on html/body/.shell — Android WebView includes the system bars in `100vh`, which broke vertical scroll. Same change is harmless on iOS.

**Setup commands** (run from `mobile/`, see `mobile/README.md` for the full flow):
```
npm install
npx cap add ios
npx cap add android
npx cap sync
npx cap open ios       # or open android
```

**Android dev build** (from `mobile/android/`, after `mobile/android/local.properties` is set with `sdk.dir=...`):
```
JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew assembleDebug
```
Debug APK lands at `mobile/android/app/build/outputs/apk/debug/app-debug.apk` (~4.4MB) — debug-signed, sideloadable, not Play-Store-uploadable. `compileSdkVersion`/`targetSdkVersion` is 35 (`mobile/android/variables.gradle`). Plugin parity with iOS — all 7 Capacitor plugins (app, network, preferences, splash-screen, status-bar, haptics, keyboard) are wired into `mobile/android/capacitor.build.gradle` + `capacitor.settings.gradle`.

**Hard prereqs before store submission:**
1. Email OTP delivery must work — upgrade Render to Starter (unblocks SMTP) or swap `_send_email()` to Resend HTTP API.
2. No more cold starts — same Render upgrade also removes the 15-min idle sleep.

**PWA bits stay**: `manifest.json` + `sw.js` at `/app/` continue to support "Add to Home Screen" on web.

## 🚧 Next up (Arabic RTL polish)
- **Support tab-label font size in Arabic**: on the topbar (customer bottom nav + provider tab bar), "الدعم" renders visibly smaller than the adjacent items ("بحث" / "تذاكري" / "رحلاتي" / "حجوزاتي"). Likely the Amiri font metrics for that word plus the JetBrains Mono base sizing don't match. Need to normalize font-size (and probably line-height) for `.nav-link.support` / `.tab-support` in the Arabic branch so the label sits flush with siblings.
- **Manifest modal arrow flips wrong in RTL**: the origin → destination line in the manifest header (`#mnf-route`) still uses the literal `→` glyph. In Arabic RTL layout, the text reorders (destination on the left, origin on the right) but the glyph stays pointing right — reading now says "destination → origin". Should either swap the glyph to `←` when `LANG === 'ar'`, or wrap the whole line in a bidi-neutral container and use a directional-aware character. Same audit needed anywhere `→` appears next to reorderable text (trip-card route line, ticket route, admin trip cards). The mobile ticket already handles this by using `↓` vertically — a hint that this class of bug already bit us once.

## 🐛 Recent fixes (most recent first)
- **Manifest 500 + trip-edit notification attribution & routing (2026-07-14 evening, `8facc77`)**: two admin-console bugs surfaced while driving the mobile UI. (1) `GET /bookings/trips/{id}/manifest` was returning 500 whenever any confirmed passenger had `phone_number IS NULL` — the `ManifestPassengerItem.phone_number` schema was still `str` (required) even though the Passenger model was made nullable in the GEN-1 sweep. Fixed by making the schema field `Optional[str] = None`; reproduces on Trip #9. Added `test_manifest_ok_when_passenger_phone_is_null` (backend suite now 96 tests). (2) `trip_edited_by_provider` notifications sent to admins carried only `provider_id` in the payload — the admin had to guess which provider. `_fanout_trip_edit` now looks up the acting provider's `full_name` and includes `provider_name` in the payload; frontend renders "Trip #N edited by \<Provider\>" (EN + AR i18n updated). (3) Notification clicks on trip-edit items routed to `admin-home` / `provider-home` and dropped the user on the default tab. New `_openAdminTripsFiltered(tripId)` / `_openProviderTripsFiltered(tripId)` helpers switch to Trips tab, set `at-q` / `pt-q` = tripId, force `time=all` (so past trips surface too), and trigger the list refresh.
- **Mobile chrome cleanup — Support to bottom bar, email to Settings (2026-07-14, `6156ad8`)**: on-device testing (iPhone) showed the topbar session block was too crowded — badge + email + notif bell + Support + signout all fighting for space. Two moves: (1) Support link migrated OUT of the topbar session block into the primary nav — added as third slot in the customer `topbar-nav` render (right-most on both desktop and mobile-bottom-bar due to source order + `justify-content: space-around`); added as `<a class="tab-support">` in `#provider-tab-bar` with `margin-inline-start: auto` on desktop (pushes right of "My Bookings") and `flex: 1` on mobile (rightmost bottom-tab cell). Topbar `.support-link` hidden via CSS for `.topbar.role-customer` and `.topbar.role-provider`; admin still sees it in the topbar (no explicit bottom-bar destination requested). (2) `#email-tag` removed from the topbar entirely (all roles). The formerly-disabled Account section in Settings now shows "Signed in as \<email\>" via `#account-email`, populated on entry through `refreshAdminSettings()`. Added new i18n key `settings.account.signed_in_as` (EN + AR); RTL rule migrated from `#email-tag` → `#account-email`. Net effect: less clutter on the phone topbar + small privacy win (email no longer leaks to shoulder-surfers on the home screen).
- **July feature batch — six-task sweep (2026-07-13 → 2026-07-14)**: end-to-end shipped as commits `325c459` … `31ea96e`, all on `feat/mobile-scaffold`, all backed by 61 new backend tests (34 → 95). Bundled here for readability:
  1. **UI polish + walk-in flow cleanup** (`325c459`, `d9b1a81`, `95844e8`, `12e4f09`, `0f033ed`) — provider walk-in now shows a single **"Confirm Payment"** CTA (billing-ref generation gated off — it could only be settled from admin, breaking flow); Support link in the topbar session block (visible for every role, not just customer); "+ New Trip" gated to Provider My Trips tab (hides on My Bookings, both on click AND on initial mount via `refreshProviderTab`); From/To labels on all four filter strips; `.status-pill.expired` grey → red. Also: **duplicate `const banner` blowup** in `renderTicket()` (introduced in `95844e8`, fixed in `12e4f09`) was a hard SyntaxError that killed the entire inline `<script>` and made the APK feel completely dead — install-over cached the broken bundle before web-side hard-refresh. Node syntax gate (`node --check` on the extracted inline JS) is now the pre-commit habit for any JS-touching change.
  2. **Ticket status bar** (`0f033ed`) — repurposed the existing delivered-banner into a single status strip at the top of the ticket. Color-coded: green **"PAID"**, amber **"PENDING PAYMENT"**, red **"EXPIRED TICKET"** (booking status `expired` OR trip departure in the past). Perforated edges (`.ticket::before/::after` at `top:-9px`) dropped in print because some browsers treated the negative offset as outside the printable margin and clipped the strip.
  3. **Passenger name rules (GEN-1)** (`45ca958`) — `_validate_passenger_names` runs inside `lock_seats()` before any seat lock. Three rules: ≥ 2 words, no in-booking dupes, no cross-booking dupes on the same active trip (`pending`/`committed_pending`/`confirmed`; expired holds free their names). Actionable error messages ("Add an additional name…"). `PassengerInput.phone_number` + `Passenger.phone_number` nullable — phone + national ID now truly optional per passenger; UI stacks three inputs per seat.
  4. **Admin per-provider capability toggles (ADMIN-2)** (`12805fd`) — three `Boolean NOT NULL DEFAULT TRUE` columns on `users` (`can_add_trips`, `can_edit_trips`, `can_delete_trips`); idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` in `_migrate_if_needed`. New `PATCH /admin/providers/{id}/capabilities` for partial updates. Provider-facing `POST /trips`, `PATCH /trips/{id}`, `DELETE /trips/{id}` all 403 with "…disabled for your account" when the relevant flag is False. Admin's `/admin/trips/*` bypasses. Admin Providers tab renders 3 checkboxes per active row; rollback on save failure.
  5. **Trip edit (GEN-2 / Task #4)** (`e96edda`) — new `service.update_trip` returns `(trip, delta)`. Partial patch on price + departure; past-departure blocked with 400. Existing bookings keep their locked `total_price` — price bump affects new bookings only. Provider path = ownership + `can_edit_trips`; admin path bypasses. Trip-edit modal on provider My Trips + admin Trips cards; `datetime-local min=now`.
  6. **Notifications subsystem (Task #5)** (`74d14e2`) — new `notifications` table (auto-created via `Base.metadata.create_all`; also imported in `conftest.py` so fresh test engines pick it up). Endpoints: `GET /notifications/me` (unread + latest 50), `POST /notifications/{id}/read`, `POST /notifications/read-all`. Emit sites wired in `_fanout_trip_edit` + `_fanout_trip_delete` (`inventory/router.py`) and inside `update_provider_capabilities`. Six event types documented in the endpoint map. Bell icon in session block (all roles), oxblood unread pill, universal `/screen-notifications` with per-type icon + title + sub + relative timestamp, click marks read and best-effort routes. Walk-in bookings' `customer_id` is the provider's own id — `create_notifications_bulk` skips falsy ids to avoid self-notify.
  7. **Manifest view + CSV export (Task #6)** (`2ecb655`) — existing `GET /bookings/trips/{id}/manifest` was open to any authenticated user; now correctly scoped (admin → any; owning provider → own; customer → 403, tested). Manifest button on provider My Trips + admin Trips cards. Modal shows seat / name / phone / ID / booking as a table. CSV export via client-side Blob download; UTF-8 BOM prepended so Excel opens Arabic names correctly; filename `manifest_trip{id}_{YYYY-MM-DD}.csv`.
  8. **Provider name on tickets** (`31ea96e`) — `TripSummary.provider_name` optional field on `TicketResponse`; ticket builder resolves `trip.provider_id → User` and drops the full name in. Frontend shows "Operated by \<Provider\>" line under the "Sudan Intercity Coach · Boarding Stub" tagline; hidden gracefully when absent.
- **Admin Reports landed (2026-06-23)**: financial + operational tables in a new fifth admin tab. Both sections show monthly + per-provider breakdowns. Confirmation date drives all bucketing — new `confirmed_at` column on `bookings` set by `confirm_payment` going forward + backfilled via `COALESCE(bill_generated_at, created_at)` on existing confirmed rows. Single endpoint `GET /admin/reports?from=&to=&provider_id=` (defaults to last 6 months). Aggregations in `backend/src/finance/reports.py` (pure functions; `period_months`, `financial_by_month`, `financial_by_provider`, `operational_by_month`, `operational_by_provider`, `build_reports`). Financial side excludes rows with `commission_amount IS NULL` entirely (count + sum); operational side includes them as real transactions. Filter strip is 280ms debounced. Each table has its own client-side Export CSV button (filenames namespace period + optional provider suffix). Mobile collapses tables to stacked cards. 22 EN+AR i18n keys under `admin.reports.*`. Spec: `docs/superpowers/specs/2026-06-23-reports-design.md`, plan: `docs/superpowers/plans/2026-06-23-reports.md`. 13 new test cases in `backend/tests/finance/test_reports.py` (61 backend tests total).
- **Postgres migrated Render → Neon (2026-06-22)**: original Render-managed Postgres hit its 90-day free-tier expiry and was suspended. We didn't pay $7/mo to recover it (no real data — only seeded demos + a handful of test bookings). New Neon free-tier Postgres provisioned; `DATABASE_URL` in Render dashboard now points at the Neon connection string. Schema rebuilt on first boot via `_ensure_schema()` + `_migrate_if_needed()`; `_bootstrap_if_empty()` re-seeded the admin + 2 providers + demo customer + sample trips/bookings exactly per `seed.py`. The `databases:` block in `render.yaml` is now dormant — Render still reads it but the web service ignores its injection because the manually-set `DATABASE_URL` env var takes precedence. **Branch gotcha discovered en route**: `render.yaml` has no `branch:` line, so Render auto-deployed from `main` (which is stuck on `0ba8e47`) instead of `feat/mobile-scaffold`. Fix was manual: dashboard → service → Settings → Branch → set to `feat/mobile-scaffold`. Documented in the Cloud deploy section.
- **Commission UI follow-up fixes (2026-06-21 evening, between initial ship and the Neon migration)**: four bugs surfaced when actually driving the UI in a browser, none caught by the backend test suite:
  1. **`api()` signature mismatch** (`df25b6e`) — every commission `api()` call was written as `api(method, path, body)` but the project convention is `api(path, {method, body: JSON.stringify(...)})`. Every commission request was hitting the literal URL "GET" / "POST" / etc — silent failure. Override creation, edit, and delete all looked dead until this landed.
  2. **`<form>` Enter-to-reload** (`8fc3853`) — the global commission card was wrapped in `<form>` with no `action`. Pressing Enter in the rate input submitted the form → page reload → the async PUT never fired. Swapped wrapper to `<div>` + `type="button"` on the save button.
  3. **`refreshAdminSettings` not called on screen entry** (`75d668d`) — gear-icon → `goto('admin-settings')` ran but never fetched data. The global form stayed hidden and overrides showed empty until the user added a new override (whose save callback triggered refresh as a side-effect). Wired refresh into the gear button's click handler.
  4. **`ON DELETE SET NULL` missing on the snapshot FK** (`cdb7fc4`) — `bookings.commission_rule_id` had a default-strict FK, so once a confirmed booking referenced a rule, DELETE on the rule returned Postgres FK violation (500). Switched the column FK to `ON DELETE SET NULL` (drops the pointer, keeps the historic `rate_kind`/`rate_value`/`amount`); idempotent `ALTER TABLE` in `_migrate_if_needed()` migrates existing deployments via `DO $$ BEGIN … END$$` block that DROPs the old constraint and re-ADDs with the new clause. Tests now enable SQLite `PRAGMA foreign_keys=ON` so an FK regression can't sneak past CI. **Coverage gap acknowledged**: the original 38-test suite hit only the API surface; we shipped to Render before clicking through the UI. The verify skill caught the FK bug; the UI driving caught the other three. Added 2 new tests (`test_delete_with_snapshot.py`, `test_admin_trips_route_id.py`).
- **`/admin/trips` exposes `route_id`** (`a2a6b86`): the frontend Add Override modal's Provider+Route picker reads `tr.route_id` from `/admin/trips` rows. `TripSearchResponse` schema was missing the field; the route dropdown silently collapsed to a single broken option. Added the field + a test.
- **Commission system landed (2026-06-21)**: three-tier rate hierarchy (`trip > provider_route > provider > global`) with immutable snapshot at booking confirmation. **Walk-in bookings are always 0% commission** — the provider sold at their own counter, the platform took no cut. New `backend/src/finance/` module: `models.CommissionRule` (UniqueConstraint on `scope, provider_id, route_id, trip_id`), `service.{resolve_rule, snapshot_commission, upsert_global, create_override, update_override, delete_override, list_overrides, _decorate_override}`, `router.py` at prefix `/admin/commissions` (GET, PUT `/global`, POST/PATCH/DELETE `/overrides`). Four new nullable columns on `bookings` (`commission_amount`, `commission_rate_kind`, `commission_rate_value`, `commission_rule_id`) backfilled by idempotent `_migrate_if_needed()` running `ALTER TABLE IF NOT EXISTS` on Postgres at lifespan. `Booking.metadata.create_all` lifted out of module scope into `_ensure_schema()` (also called from lifespan) so importing `src.main` no longer opens a DB connection — tests can swap engines via dependency override. Snapshot hook lives in `admin.service.confirm_payment` (covers both admin confirm AND provider walk-in cash confirm via shared call site). Provider `/bookings/provider/mine` response gains `commission_amount` + `net_amount` fields. Frontend: gear icon (`#settings-btn`) in topbar (admin-only via `paintChrome` gate) opens new `#screen-admin-settings`, structured as a forward-compatible section list (`<section class="settings-section">`). First section is Commissions (global form + overrides list + Add/Edit modal at `#commission-override-modal` with scope pills + conditional provider/route/trip selects). Second section is Account, disabled-with-coming-soon placeholder for the future password-reset work. Provider Bookings tab gains per-row Commission + Net lines (with `(walk-in)` tag on walk-ins) and a totals footer (`#provider-bookings-footer`) summing Gross/Commission/Net over confirmed rows in the current filter. 42 new EN+AR i18n keys under `settings.*`, `commission.*`, `commission.modal.*`, `provider.commission.*`. Spec at `docs/superpowers/specs/2026-06-21-commissions-design.md`, plan at `docs/superpowers/plans/2026-06-21-commissions.md`. Backend test suite now exists (`backend/tests/`, pytest 8.3 + httpx 0.27 + SQLite in-memory + StaticPool + fresh-engine-per-test isolation); 38 tests passing across resolve, snapshot, service helpers, endpoints, confirm-path integration, and provider visibility.
- **Android first build + back button + scroll fix (2026-06-19)**: Capacitor 6 wrap now builds + runs on Android (Pixel emulator API 35 via Android Studio; debug APK sideloadable on personal device — `mobile/android/app/build/outputs/apk/debug/app-debug.apk`, ~4.4MB). Changes that landed: (1) `mobile/android/variables.gradle` bumped `compileSdkVersion` + `targetSdkVersion` 34→35 (Play Store requirement; only API 35+ accepted for new submissions). (2) `mobile/android/capacitor.build.gradle` + `mobile/android/capacitor.settings.gradle` synced to include `:capacitor-haptics` + `:capacitor-keyboard` — these plugins shipped on iOS but weren't in the original Android scaffold, so `npx cap sync android` backfilled them (haptics permissions auto-merged via plugin manifest → `android.permission.VIBRATE` now in merged manifest). (3) Android hardware/gesture back button wired via `Plugins.App.addListener('backButton', ...)` — close any open `.modal-bg.show` → pop `STATE.history` via existing `back()` → fall through to `App.exitApp()` at root. iOS unaffected (event never emitted). (4) Scroll fix: html/body `min-height: 100vh`→`100dvh`, `overflow-x: hidden`→`clip`, dropped `overscroll-behavior-y: none`; same `100vh`→`100dvh` swap on `.shell`. Android WebView wasn't scrolling on any screen because `100vh` includes Android system bars (taller than the visible viewport) so the WebView thought everything fit. **Required env on this machine**: `mobile/android/local.properties` with `sdk.dir=~/Library/Android/sdk` (gitignored, machine-specific). Build command from `mobile/android/`: `JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew assembleDebug`. Pixel + API 35 (CinnamonBun/Android 16, arm64-v8a) is fine for dev — `targetSdk` is "tested against", not "runtime ceiling," so forward-compatible.
- **Mobile responsive UI pass + native-feel polish landed on iPhone (2026-06-15)**: Capacitor 6 wrap is now running on iPhone 14 Pro Max via Xcode dev signing. Two new Capacitor plugins linked: `@capacitor/haptics` (global tap-feedback via document-level capture-phase click listener — LIGHT impact on every button, MEDIUM on `.cta`, SUCCESS/ERROR notification on toast) and `@capacitor/keyboard` (`resize: 'body'` in `capacitor.config.ts` so focused inputs aren't hidden by the keyboard). `paintChrome()` calls `applyStatusBarStyle(role)` to flip LIGHT/DARK status-bar text per role chrome (provider/admin navy → LIGHT, customer paper → DARK). Viewport meta now `maximum-scale=1, user-scalable=no` — kills iOS focus auto-zoom. Massive `@media (max-width: 640px)` block at line ~216: top bar shrunk + email truncated + role badge hidden; customer nav becomes a **fixed bottom tab bar** (`position: fixed; bottom: 0` with safe-area-inset-bottom padding); same treatment applied to admin (Providers/Trips/Bookings/Payments) and provider (My Trips/My Bookings) tab strips for consistency. Display fonts shrunk system-wide (h1 56→32, trip-card route 28→17, price 32→18, ticket city 36→16, etc). Ticket card mobile redesign: cities stack vertically on the LEFT, QR floats on the RIGHT via `position: absolute`, downward arrow rendered via `::before content: '↓'` (no transform). Origin/destination free-text inputs across 10 places converted to `<select>` dropdowns — 16 Sudanese cities, alphabetized, renders as native iOS wheel picker (filter selects have "All cities" optional placeholder, required selects have "Select a city"). Canvas `padding-bottom: calc(80px + env(safe-area-inset-bottom))` reserved for screens that show a bottom bar — customer scoped by role chrome (the bar is visible on every customer-* screen, not just home), provider/admin scoped by `body[data-screen=*-home]`. Email tag always renders LTR even in Arabic mode. Welcome screen flex-centered to kill rubber-band wobble on iOS. **Known CSS quirk**: the mobile `@media` block sits at line ~216, BEFORE many desktop ticket-card rules at line 1049+. At equal specificity, source order wins → desktop overrides mobile. Worked around for `.ticket-route .city` with a `.ticket` prefix that bumps specificity. Long-term fix: move the mobile `@media` block to the END of the style block. **Still pending**: Android side completely untouched (scaffold ready but Android Studio first-launch SDK download not yet run). Arabic improvements queued — replace Amiri with a more app-native Arabic font (Cairo/Tajawal/IBM Plex Sans Arabic), bilingual city names, and Arabic content on ticket print.
- **Mobile scaffold + Phase 0 hardening landed** (paused 2026-06-14 on user's macOS upgrade so Xcode installs): `/mobile/` directory with `package.json` (Capacitor 6.2.1), `capacitor.config.ts`, `.gitignore`, `README.md` — pointed at `../frontend/` so the web and native shells share one codebase. `mobile/ios/App/` + `mobile/android/` scaffolds generated. Placeholder icon + splash composited from `frontend/icon.svg` (qlmanage → PIL), 87 Android + 10 iOS variants via `@capacitor/assets`. `npx cap sync` ran cleanly (iOS pod-install step deferred — needs Xcode). Frontend hardened so the *same* `index.html` works in both contexts: API base URL resolver (Capacitor → `TAZ_API_NATIVE_DEFAULT = 'https://tazkirati-web.onrender.com'`, web → `location.origin`), persistent auth via `@capacitor/preferences` on native, cold-start "Waking up the server…" toast (2.5s threshold, one-shot per session, EN+AR), long-poll pause/resume on `App.appStateChange`, service worker gated off on native, QR lib bundled at `frontend/vendor/qrcode.min.js` (was CDN). Backend `cors_origins` auto-appends Capacitor webview schemes. **Resume checklist** for next session is in the `project-mobile-launch` memory.
- **OTP rate limit + cooldown UI**: 30-second cooldown between resends + 3-per-hour cap on the backend; resend button shows a live `Resend in 23s` countdown and is disabled until it expires.
- **Cash confirm on the booking screen**: provider walk-in flow now exposes the green `Confirm Cash Payment` CTA directly on the post-lock panel alongside `Generate Billing Reference`. One click confirms + opens the ticket modal with the "Payment Confirmed" stamp.
- **Provider tab filters**: both `My Trips` and `My Bookings` gain admin-style filter strips (`q` / origin / destination / time-or-status), 280ms debounced. Backend `/trips/mine` and `/bookings/provider/mine` accept the matching query params.
- **`confirm_payment` mints billing ref when missing**: cash walk-ins that skipped billing intent now get a `BOK-XXXX-XX` ref + `bill_generated_at` at confirmation time, so every confirmed booking is QR-printable.
- **Top-bar UX polish**: nav links now render as bigger Fraunces serif chips with terracotta accent on active. "My Tickets" carries a count badge for pending / committed_pending bookings (refreshed on login + after every lock/billing). Language toggle scaled up. Awkward "PASSENGER · SEARCH" subhead hidden on all main landing screens — crumb only shows on sub-screens.
- **Register password confirmation**: extra "Confirm password" field with client-side mismatch check and translated toast.
- **Admin trip filtering**: Trips tab now has a filter strip matching Bookings — `q` / origin / destination / time (upcoming|past|all), 280ms debounced.
- **Provider cash confirmation (P-PAY-03)**: provider can one-shot confirm a walk-in on their own trip via the new endpoint; renders as a green "Confirm Payment (Cash)" button on every unpaid walk-in row in the Provider Bookings tab.
- **Comprehensive Arabic translation**: every visible control (~130 keys) translated. Adds `tStatus()` / `tChannel()` for backend enums, `data-i18n-placeholder` for input placeholders, and locale-aware date formatting.
- **Future-only trips**: `POST /trips` refuses past `departure_time` (400). Frontend datetime input has `min=now+5m`.
- **Recurring trips**: Add Trip modal exposes Once / Daily / Weekly / Custom-days picker; service expands the pattern and creates N trips atomically.
- **EN / Arabic toggle**: `[data-i18n]` runtime + RTL direction flip + Amiri font for Arabic display.
- **Signout persistence fix**: `[hidden] { display: none !important; }` rule so logged-out chrome doesn't linger when CSS has `display: flex`. Email tag explicitly cleared on logout too.
- **Live indicator removed** from the subhead (was confusing). `setConn()` kept as a no-op so existing call sites stay intact.
- **Admin reconciliation on startup**: lifespan compares the admin row to `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars and updates it if they've changed. Means rotating admin creds in Render's UI actually takes effect on next deploy without DB access.
- **Re-registration on unverified emails**: stale unverified record gets overwritten with fresh password + new OTP. 409 only fires on fully verified accounts.
- **SMTP transport**: real email delivery via `smtplib` when `SMTP_*` env vars are set, console fallback otherwise. (Currently blocked on Render free tier — see Known Limitations.)
- **Auto-seed**: lifespan startup seeds the DB if no admin exists. Required because free tier has no Shell to run `python seed.py` manually.
- **Env-overridable admin creds**: `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars take precedence over committed defaults in `seed.py`.
- **Dev OTP gate**: `dev_otp` no longer in API responses when `DEBUG=false`.
- **Welcome screen hardened**: credentials display moved behind `?demo=1` query param.
- **Provider name display**: `inventory.service.decorate_trip_row()` joins User → displays "Operated by ..." on customer + admin trip cards.
- **Dockerfile relocated** to repo root so manual Web Service flow on Render finds it without configuration.
- **`postgres://` URL normalization** in `database.py` for Render-style connection strings.
- **Timer UTC parsing**: `parseUtc()` helper in frontend appends `Z` to naive UTC ISO strings.

## 🚫 Do not modify
- `backend/src/booking/tasks.py` — the Reaper. Golden.
- `backend/docker-compose.yml` — local Postgres only.
