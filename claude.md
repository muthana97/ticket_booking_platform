# MVP Technical Scope & Guardrails (Claude Code Context)

## 🎯 What this build is
A web-portal MVP that demonstrates every role in `Context/requirements.v2.md`, **minus payments (PAY-04 / SYS-01) and cancellations (CAN-01..03)**. Designed to deploy to Render's free tier first (20-30 concurrent users), upgrade to paid when stakeholders sign off.

Auth is currently **email + password for all roles** (will be realigned to spec — phone-OTP for customer/provider, email+password for admin — in a later sprint once SMS/SMTP credentials are decided). Email + phone OTP delivery infra design is documented in chat history; not yet wired.

## 👥 Roles & data isolation (live)
| Role | Status model | Access |
|---|---|---|
| Customer | `active` after email verification | Search trips · book seats · view own tickets |
| Provider | `pending` → admin approves → `active` (or `blocked`) | Manage own trips · walk-in bookings on own trips · view own bookings |
| Admin | seeded `active` only | Approve/block providers · view all trips · search all bookings · confirm pending payments |

**Provider data isolation is enforced server-side** — `Trip.provider_id` checked on `DELETE /trips/{id}` and `POST /bookings/walkin`. A provider cannot see or touch another provider's trips/bookings.

## 🗺️ Endpoint map
**Auth:** `POST /auth/register` · `POST /auth/verify-email` · `POST /auth/resend-otp` · `POST /auth/login` · `GET /auth/me`

**Trips:** `GET /trips/search` (open) · `GET /trips/mine` (active provider, own trips only) · `POST /trips` (active provider) · `DELETE /trips/{id}` (active provider, own only)

**Bookings:**
- `POST /bookings/lock` (consumer) · `POST /bookings/walkin` (provider, on own trips only)
- `POST /bookings/intent/billing` (Path B billing reference)
- `GET /bookings/{id}/ticket` (re-fetch ticket payload, no state mutation)
- `GET /bookings/me` (customer's own consumer bookings)
- `GET /bookings/provider/mine` (active provider's bookings, both channels)
- `GET /bookings/trips/{id}/seats/stream` (long-polling, version-stamped)
- `GET /bookings/trips/{id}/manifest`

**Admin:** `GET /admin/providers` · `POST /admin/providers/{id}/approve|block` · `GET /admin/trips` · `DELETE /admin/trips/{id}` · `GET /admin/bookings` (filterable by `status`, `q`, `origin`, `destination`) · `GET /admin/payments/pending` · `POST /admin/payments/{id}/confirm`

## ✂️ Deliberately deferred (V2)
- Path A direct payments (SYS-01) — admin manual `POST /admin/payments/{id}/confirm` is the MVP substitute.
- Cancellations + refunds (CAN-01..03).
- Commission rules + campaigns (Part 3.4–3.5).
- Financial / operational reports (3.6–3.7).
- Phone-OTP login (AUTH-01, P-AUTH-01) — currently email+password for all roles.
- Real SMS / email transport (SYS-02). Today: console logs + `dev_otp` echo in response.
- Arabic RTL (NFR-15).
- Audit log (A-MON-04).
- Offline manifest cache (NFR-13).

## 🛠️ MVP Hard Requirements (still binding)
1. **Shared Locking Core** — `POST /bookings/lock` and `POST /bookings/walkin` both call `service.lock_seats(...)` atomic transaction.
2. **Fixed Fleet Seating** — only 45-seat (10×2x2 + 5-back) or 48-seat (3 front + 10×2x2 + 5-back). Enforced in `inventory.service.generate_seat_names`.
3. **Stakeholder Ticket Output** — `TicketResponse` carries booking, trip, passengers, seat map, `BOK-XXXX-XX` billing ref, `delivered_to` (simulated email), and `qr_payload` (TKT-04 — frontend renders into a real QR via qrcodejs).
4. **Real-time State Sync** — long-polling at sub-second latency on change.
5. **Provider data isolation** — server-side gate on cross-provider operations.
6. **Admin oversight** — provider approval, trip oversight, all-bookings search/filter, manual payment confirmation.

## 🧪 Demo credentials (from `seed.py`)
| Role | Email | Password |
|---|---|---|
| Admin | `admin@tazkirati.app` | `tazkirati-admin-2026` |
| Customer | `passenger@tazkirati.app` | `passenger123` |
| Provider — Nile Coach Co. | `operator@tazkirati.app` | `operator123` |
| Provider — SudanBus Express | `ops@sudanbus.app` | `operator123` |

Two providers ship by default so data-isolation can be demoed end-to-end. Three sample bookings on the customer account: 1 committed_pending, 1 confirmed (upcoming), 1 confirmed (past — populates the "Past" section of My Tickets).

## 🚀 Cloud deploy (Render free tier first)

The repo ships a `render.yaml` blueprint at the root. To deploy:
1. Connect this repo to Render.
2. Render auto-creates the `tazkirati-web` service + the `tazkirati-db` Postgres from the blueprint.
3. Set `CORS_ALLOWED_ORIGINS` to the deployed URL (e.g. `https://tazkirati-web.onrender.com`).
4. Container builds from `backend/Dockerfile`, serves the API + the frontend at `/app/`.
5. On first boot the Reaper task starts in-process (the `lifespan` hook in `main.py`).

**Free tier limits we're knowingly accepting for stakeholder testing:**
- Web service sleeps after 15 min idle (~30s cold-start to wake).
- Postgres expires after 90 days, then is deleted.
- 1 worker only (which is *why* the Reaper-in-process pattern is safe).

**Upgrade path (when stakeholders sign off):**
- Bump `plan: free` → `plan: starter` on both `services` and `databases` in `render.yaml`.
- Bump uvicorn workers in `Dockerfile` CMD: `--workers 2`.
- When workers > 1, **extract the Reaper** out of `main.py`'s `lifespan` into a separate Render `worker` service so it doesn't multiply across uvicorn workers. The current Reaper code is already self-contained in `backend/src/booking/tasks.py:cleanup_expired_bookings()`.
- Update env: `DB_POOL_SIZE=10`, `DB_POOL_MAX_OVERFLOW=20`.

## 📱 Mobile path
The frontend ships PWA bits: `manifest.json` + `sw.js` at `/app/`. Users can "Add to Home Screen" today and get an installable, fullscreen app — same codebase. When a native shell is needed, wrap the same HTML in **Capacitor** for App Store distribution (no UI rebuild). Not in this sprint.

## 🐛 Known fixes shipped this iteration
- Past tickets show up in "My Tickets · Past" via `trip.departure_time < now()` flag returned by `/bookings/me`.
- QR codes encode `TAZ|<booking_id>|<billing_ref>|<seats>|<departure>|<status>` — scanned at boarding to verify.
- Seed bug fixed: `_build_seats` now flushes so subsequent booking-sample queries see the new seats.

## 🚫 Do not modify
- `backend/src/booking/tasks.py` — the Reaper. Golden.
- `backend/docker-compose.yml` — local Postgres only.
