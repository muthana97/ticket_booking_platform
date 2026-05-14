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
│   ├── .venv/                   # Python 3.12+ virtual environment
│   ├── docker-compose.yml       # PostgreSQL 15 container config
│   ├── src/
│   │   ├── main.py              # App entry point, router registration
│   │   ├── config.py            # Settings loader (JWT, OTP, & Lock constraints)
│   │   ├── database.py          # SQLAlchemy engine & session generator
│   │   ├── inventory/           # SRCH-01 & SEAT-01 logic
│   │   ├── auth/                # AUTH-01 & JWT utility logic
│   │   ├── booking/             # SEAT-02 & SEAT-04 "Hot Path" logic
│   │   └── common/              # Shared utilities
├── .gitignore                   # Ignoring .venv, .env, and __pycache__
└── context.md                   # This file
4. Comprehensive File Manifest (Latest Changes)
🏗️ Infrastructure & Config
backend/src/config.py: Unified settings including ALGORITHM (HS256), ACCESS_TOKEN_EXPIRE_MINUTES, and SEAT_LOCK_DURATION_MINUTES.

backend/src/main.py: Updated to include inventory_router, auth_router, and the new booking_router.

🔐 Auth Module (src/auth/)
utils.py: (NEW) Handles JWT creation using the system SECRET_KEY.

router.py: (UPDATED) verify-otp now issues a real signed JWT containing the user ID as the subject (sub).

🎟️ Booking Module (src/booking/)
schemas.py: (NEW) Defines BookingLockRequest for selecting trip_id and seat_numbers.

service.py: Implements lock_seats() using with_for_update() to satisfy NFR-05.

router.py: (NEW) Exposes POST /bookings/lock for atomic seat reservation.

5. Current Operational State
Identity (IAM): Real JWT issuance is functional (Phase 2 @ 80%).

Inventory: Models and search logic (SRCH-01) complete.

Booking Engine: "Hot Path" initialized. Atomic locking logic is wired to an HTTP endpoint (Phase 4 @ 25%).

Database: All 8 tables (including bookings and passengers) exist and are active in the Docker container.

6. Next Steps (Priority Order)
JWT Dependency: Implement get_current_user to secure the /bookings/lock endpoint.

Data Seeding: Populate the database with test trips/buses to verify the seat locking end-to-end.

Dual-Path Payment: Begin logic for Bank of Khartoum (Path A) and Billing References (Path B).
