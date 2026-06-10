# MVP Technical Scope & Guardrails (Claude Code Context)

## 🎯 What this build is
A web-portal MVP that demonstrates every role in `Context/requirements.v2.md`, **minus payments (PAY-04 / SYS-01) and cancellations (CAN-01..03)**. Currently deployed to Render's free tier for stakeholder testing; upgrade to paid when sign-off comes.

Auth is currently **email + password for all roles** (deferred realignment to phone-OTP for customer/provider per AUTH-01 / P-AUTH-01).

## 👥 Roles & data isolation (live)
| Role | Status model | Access |
|---|---|---|
| Customer | `active` after email verification | Search trips · book seats · view own tickets |
| Provider | `pending` → admin approves → `active` (or `blocked`) | Manage own trips · walk-in bookings on own trips · view own bookings |
| Admin | seeded `active` only (or env-overridden, see below) | Approve/block providers · view all trips · search all bookings · confirm pending payments |

**Provider data isolation is enforced server-side** — `Trip.provider_id` checked on `DELETE /trips/{id}` and `POST /bookings/walkin`. A provider cannot see or touch another provider's trips/bookings. Trip rows in customer + admin views display the operating provider's name via `inventory.service.decorate_trip_row()`.

## 🗺️ Endpoint map
**Auth:** `POST /auth/register` · `POST /auth/verify-email` · `POST /auth/resend-otp` · `POST /auth/login` · `GET /auth/me`

**Trips:** `GET /trips/search` (open) · `GET /trips/mine` (active provider, own trips only — accepts `q` / `origin` / `destination` / `time`) · `POST /trips` (active provider — accepts a `repeat` pattern + `days_of_week` + `end_date`; returns `TripsCreatedResponse` with the list of created trips) · `DELETE /trips/{id}` (active provider, own only)

**Bookings:**
- `POST /bookings/lock` (consumer) · `POST /bookings/walkin` (provider, on own trips only)
- `POST /bookings/intent/billing` (Path B billing reference)
- `POST /bookings/{id}/provider-confirm` (active provider on their own trip — one-shot cash confirm for walk-ins; P-PAY-03)
- `GET /bookings/{id}/ticket` (re-fetch ticket payload, no state mutation)
- `GET /bookings/me` (customer's own consumer bookings)
- `GET /bookings/provider/mine` (active provider's bookings, both channels — accepts `q` / `origin` / `destination` / `status`)
- `GET /bookings/trips/{id}/seats/stream` (long-polling, version-stamped)
- `GET /bookings/trips/{id}/manifest`

**Admin:** `GET /admin/providers` · `POST /admin/providers/{id}/approve|block` · `GET /admin/trips` (filterable by `q`, `origin`, `destination`, `time`, `provider_id`) · `DELETE /admin/trips/{id}` · `GET /admin/bookings` (filterable by `status`, `q`, `origin`, `destination`) · `GET /admin/payments/pending` · `POST /admin/payments/{id}/confirm`

## ✂️ Deliberately deferred (V2)
- Path A direct payments (SYS-01) — admin manual `POST /admin/payments/{id}/confirm` is the MVP substitute.
- Cancellations + refunds (CAN-01..03).
- Commission rules + campaigns (Part 3.4–3.5).
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
8. **Provider cash confirmation** (P-PAY-03) — `POST /bookings/{id}/provider-confirm` lets an active provider one-shot cash-confirm a walk-in on their own trip: status `pending|committed_pending` → `confirmed`, `payment_method='cash'`, seats `locked` → `booked`. A billing reference + `bill_generated_at` is minted on confirmation if absent, so cash bookings still get a printable ticket + QR. Cross-provider attempts return 403. Surfaced two ways in the UI: inline `Confirm Cash Payment` CTA on the post-lock booking panel **and** per-row button on the Provider Bookings tab.
9. **Email-OTP rate limit** (NFR-08 / ERR-04) — `_generate_email_otp` enforces 30-second cooldown between requests for the same email + max 3 codes per email per hour. Returns 429 with a human-readable detail. Frontend mirrors the cooldown via a live `Resend in 23s` countdown on the resend button.

## 🌐 Localization (EN / Arabic)
- Topbar carries an `EN / عربي` toggle (Fraunces 14px, prominent border). Choice persists in `localStorage` (`taz.lang`).
- Translation runtime: a 130+ key `I18N` table + `applyLanguage()` walks every `[data-i18n]` element and swaps `textContent`. `data-i18n-html="1"` opts the element into `innerHTML` (for strings with embedded links). `data-i18n-placeholder` covers input placeholders.
- Helpers: `t(key)`, `tStatus(s)` and `tChannel(s)` for backend-supplied enum strings (e.g. `status.pending`, `channel.walkin`).
- Arabic mode flips `<html dir="rtl">`, swaps display font to **Amiri** (Google Fonts), and forces LTR direction on numeric / mono elements (seat map, prices, billing refs, codes). Dates render in Arabic locale (Arabic month names + Arabic-Indic numerals); money stays en-US digits for receipt clarity.
- Coverage: welcome, sign-in, register (incl. password confirm), verify-email, provider-pending, customer search + trip cards, booking screen (panels, legend, lock/walk-in CTAs, countdown), My Tickets sections + pills, provider home tabs + bookings + add-trip modal (incl. repeat picker, day-of-week chips, end-date), admin console (4 tabs, both filter strips, all row actions), ticket modal (every field, stamps, delivered banner, buttons). Status + channel pills translate per-row.

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

## 🚀 Cloud deploy (Render free tier)

The repo ships a `render.yaml` blueprint at the root. Dockerfile lives at repo root (`./Dockerfile`) so both Render's Blueprint flow and manual Web Service flow find it.

**Deploy from scratch:**
1. Connect this repo to Render.
2. Render dashboard → New + → **Blueprint** → select repo → Apply.
3. Render auto-provisions `tazkirati-web` (Docker) + `tazkirati-db` (free Postgres 15). `DATABASE_URL` wires automatically; `SECRET_KEY` auto-generates.
4. In the web service Environment tab, set the `sync: false` env vars manually:
   - `CORS_ALLOWED_ORIGINS=<deployed-url>`
   - `ADMIN_EMAIL` + `ADMIN_PASSWORD` (optional — override the seed defaults)
   - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` (optional — see Known Limitations)
5. **Auto-seed**: on first boot, `_bootstrap_if_empty()` in `main.py` lifespan runs `seed.py` if no admin exists. Required because free tier has no Shell to run scripts manually. Idempotent across cold starts.

**Free-tier facts to know:**
- Web service sleeps after 15 min idle (~30s cold-start).
- Postgres expires after 90 days then is deleted.
- 1 worker only (which is *why* the Reaper-in-process pattern is safe).
- **Outbound SMTP is blocked** — see Known Limitations.

**Upgrade path (when stakeholders sign off):**
- Bump `plan: free` → `plan: starter` on both services in `render.yaml`.
- Bump uvicorn `--workers` in `Dockerfile` CMD.
- When workers > 1, **extract the Reaper** into a separate `worker` service so it doesn't multiply across uvicorn workers. Reaper code is self-contained in `backend/src/booking/tasks.py`.
- Update env: `DB_POOL_SIZE=10`, `DB_POOL_MAX_OVERFLOW=20`.
- Outbound SMTP unblocks on paid plans.

## ⚠️ Known production limitations (Render free tier)

| Limitation | Impact | Workaround |
|---|---|---|
| Outbound SMTP blocked (port 25 / 587 / 465) | Email OTP `_send_email()` returns `[EMAIL] SMTP delivery failed: OSError(101, 'Network is unreachable')`. Falls back to `[EMAIL-OTP-CONSOLE]` log line. Users can't verify via email. | (a) Upgrade to paid Render plan, or (b) switch from SMTP to an HTTP-API email service (Resend / SendGrid / Mailgun). Resend is the easiest swap. |
| No Shell tab | Can't run `python seed.py` manually. | Auto-seed on lifespan startup (already implemented). |
| Service sleeps after 15 min | First request after sleep takes ~30s. | Acceptable for stakeholder demo; upgrade removes it. |
| Postgres 90-day expiry | Free DB is wiped after 90 days. | Render emails a warning; back up via `pg_dump`, or upgrade before then. |

## 📱 Mobile path
Frontend ships PWA bits: `manifest.json` + `sw.js` at `/app/`. Users can "Add to Home Screen" for an installable, fullscreen app on iOS/Android — same codebase. When native shell is needed, wrap with **Capacitor** for App Store distribution (no UI rebuild).

## 🐛 Recent fixes (most recent first)
- **Loading indication everywhere**: a `withLoading()` helper disables async-bound buttons (sign in, register, verify, resend, search, lock, billing, cash confirm) and shows an inline spinner during the request. Plus a thin terracotta progress bar at the top of the viewport that pulses while any request is in flight. Was added because users were spamming OTP resends thinking the server hadn't responded.
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
