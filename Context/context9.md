Project Context: Ticket Booking Platform (Active Development)
1. System Overview & Objectives
Goal: A high-concurrency, multi-provider marketplace for bus tickets featuring real-time seat locking and dual-path payment integration (Bank of Khartoum & Billing Reference).
Core Logic: Atomic seat management using PostgreSQL row-level locking (SELECT ... FOR UPDATE) to prevent double-booking. The system now includes an automated "Reaper" to manage seat lifecycle.

2. Technical Stack (Live)
Layer	Technology
Backend	FastAPI (Python 3.12+) running via Uvicorn
Database	PostgreSQL 15 (Docker: ticket_booking_db)
ORM	SQLAlchemy with psycopg2-binary
Security	JWT signed via python-jose; OTP-based authentication
Concurrency	Row-level locking (with_for_update) in booking service
Worker	Async lifespan background task (The Reaper)
3. Directory Structure (Monorepo)
Plaintext
ticket_booking_platform/
├── backend/
│   ├── .env                     # DATABASE_URL, SECRET_KEY, JWT_ALGORITHM
│   ├── docker-compose.yml       # PostgreSQL 15 container config
│   ├── seed.py                  # Data population script for testing
│   ├── test_lock.py             # Concurrency race-condition test script
│   └── src/
│       ├── main.py              # App entry point & background task orchestration
│       ├── config.py            # Settings loader (JWT & Lock constraints)
│       ├── database.py          # SQLAlchemy engine & session generator
│       ├── auth/                # OTP & JWT logic (Phase 2)
│       ├── inventory/           # Trip search & seat map logic (Phase 3)
│       ├── booking/             # Atomic locking & Reaper logic (Phase 4)
│       └── common/              # Shared utilities
4. Comprehensive File Manifest
🏗️ Infrastructure & Config
backend/seed.py: [LIVE] Populates Routes, Buses, Trips, and Seats for testing.

backend/test_lock.py: [LIVE] Script used to verify concurrency; confirmed 100% reliable.

🔐 Auth Module (src/auth/)
router.py / service.py: [LIVE] Implements OTP verification and JWT issuance.

dependencies.py: [LIVE] Provides get_current_user for securing endpoints.

🎟️ Booking Module (src/booking/)
models.py: [LIVE] Contains Booking with expires_at, status, and seat_ids (JSON).

service.py: [LIVE] Atomic lock_seats logic using with_for_update.

tasks.py: [LIVE] The Reaper function; runs every 60s to release expired locks (SEAT-04).

router.py: [LIVE] POST /bookings/lock secured by JWT; verified for high-concurrency.

🚀 Main Entry (src/main.py)
main.py: [LIVE] Implements the lifespan manager to start/stop the Reaper background task.

5. Current Operational State
Identity (IAM): 100% Complete. Real JWT issuance and verification functional.

Inventory: 100% Complete. Database seeding and trip search logic functional.

Booking Engine: 100% Complete. Atomic locking verified via race-condition tests. Automatic seat-release (Reaper) is active.

Payment Integration: 0% (Phase 5). CURRENT GOAL. Ready to implement dual-path (BoK & Billing Reference).

6. Next Steps (Priority Order)
Payment Schema: Extend Booking or create Payment model to support payment_method, billing_reference, and amount.

Path A Integration: Implement Bank of Khartoum (BoK) API client logic.

Path B Logic: Implement the 30-minute window for billing reference payments (PAY-04).

Manifest Generation: Build the manifesto (passenger list) logic (MAN-02).

AI Assistant Note: Concurrency is verified. User A vs User B race condition results in 200/400 distribution as intended. Do not modify locking logic without re-running test_lock.py.
