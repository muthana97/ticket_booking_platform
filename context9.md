Project Context: Ticket Booking Platform (Active Development)
1. System Overview & Objectives
Goal: A high-concurrency, multi-provider marketplace for bus tickets with real-time seat locking and dual-path payment integration (BoK & Billing Reference).

Core Logic: Atomic seat management using PostgreSQL row-level locking (SELECT ... FOR UPDATE) to prevent double-booking—100% reliability for seat holds.

Architecture: Monorepo—Backend (FastAPI), plus placeholders for Frontend & Mobile.

2. Technical Stack (Live)
Layer	Technology
Backend	FastAPI (Python 3.12+) running via Uvicorn
Database	PostgreSQL 15 (Docker container: ticket_booking_db)
ORM	SQLAlchemy with psycopg2-binary
Security	JWT (JSON Web Tokens) signed via python-jose; passlib for hashing
Configuration	Pydantic Settings V2 with .env
Concurrency	Row-level locking (with_for_update) in booking service

3. Directory Structure (Monorepo)
Plaintext
ticket_booking_platform/
├── backend/
│   ├── .env                     # DATABASE_URL, SECRET_KEY, DEBUG, JWT_ALGORITHM
│   ├── .venv/                   # Python 3.14 (Active Dev Env)
│   ├── docker-compose.yml       # PostgreSQL 15 container config
│   ├── seed.py                  # (ACTIVE) Data population script for testing
│   ├── src/
│   │   ├── main.py              # App entry point, router registration
│   │   ├── config.py            # Settings loader (JWT, OTP, & Lock constraints)
│   │   ├── database.py          # SQLAlchemy engine & session generator
│   │   ├── inventory/           # SRCH-01 & SEAT-01 logic
│   │   ├── auth/                # AUTH-01, JWT logic, & Security Dependencies
│   │   ├── booking/             # SEAT-02 & SEAT-04 "Hot Path" logic
│   │   └── common/              # Shared utilities

4. Comprehensive File Manifest (Latest Changes)
🏗️ Infrastructure & Config
backend/seed.py: (NEW) Implements logic to populate Routes, Buses, Trips, and Seats to unlock Phase 4 testing.

🔐 Auth Module (src/auth/)
dependencies.py: Implements get_current_user to decode JWTs and inject the authenticated user.
service.py: verify_otp returns a full User object to facilitate JWT creation.
router.py: Successfully issues signed JWTs.

🎟️ Booking Module (src/booking/)
service.py: (REVIEWED) Implements atomic seat locking with `with_for_update`. Logic for 10-15 min timeout is delegated to the Booking entity.
models.py: (VERIFIED) Booking model contains `expires_at` and `seat_ids` (JSON) to track lock state.
router.py: Requires valid Bearer Token for POST /bookings/lock.

5. Current Operational State
Identity (IAM): Real JWT issuance and verification are 100% functional (Phase 2 Complete).
Inventory: Models and search logic complete. Database now has a functional seeding path (Phase 3 @ 100% local/test).
Booking Engine: "Hot Path" initialized. Atomic locking logic is wired and secured (Phase 4 @ 45%).

6. Next Steps (Priority Order)
Concurrency Verification: Perform a "Load Test" on the seat locking logic to ensure zero-fail holds.
Seat State Management: Implement the background "reaper" to release seats from expired bookings (NFR-12).
Dual-Path Payment: Begin logic for Bank of Khartoum (Path A) and Billing References (Path B).
