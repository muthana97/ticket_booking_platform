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
│   ├── seed.py                  # (NEW) Data population script for testing
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

backend/src/main.py: Fully wired with all module routers; verified fixed imports for booking_router.

🔐 Auth Module (src/auth/)

dependencies.py: (NEW) Implements get_current_user to decode JWTs and inject the authenticated user into protected routes.

service.py: (UPDATED) verify_otp now returns a full User object (instead of boolean) to facilitate JWT creation.

router.py: (VERIFIED) Successfully issues signed JWTs; verified fixed imports for utils.

🎟️ Booking Module (src/booking/)

router.py: (SECURED) Now requires a valid Bearer Token for POST /bookings/lock via FastAPI Dependency Injection.

5. Current Operational State
Identity (IAM): Real JWT issuance and verification are 100% functional (Phase 2 Complete).

Inventory: Models and search logic (SRCH-01) complete.

Booking Engine: "Hot Path" initialized. Atomic locking logic is wired to an HTTP endpoint and secured by IAM (Phase 4 @ 40%).

Database: All 8 tables exist; verified ability to manually seed Users and OTPs for testing.

6. Next Steps (Priority Order)
Data Seeding: Execute seed.py to populate test trips/buses to verify the seat locking end-to-end.

Seat State Management: Implement logic to automatically release expired seat locks (NFR-05).

Dual-Path Payment: Begin logic for Bank of Khartoum (Path A) and Billing References (Path B).
