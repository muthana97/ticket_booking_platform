Project Context: Ticket Booking Platform
1. System Overview
A real-time, multi-provider marketplace for bus ticket booking.

Core Goal: High-concurrency seat management and dual-path payment integration.

Architecture: Monorepo. Backend is a FastAPI service; Frontend/Mobile directories are placeholders.

Primary Constraints: 100% reliability for double-booking prevention (Atomic Transactions) and 99% system uptime.

2. Directory Structure Status
The project is organized to isolate the service logic from the root configuration.

Plaintext
ticket_booking_platform/
├── backend/
│   ├── .env                    # Postgres & Secret Key config
│   ├── .venv/                  # Python 3.x isolated environment
│   ├── docker-compose.yml      # Manages the PostgreSQL 15 container
│   ├── src/
│   │   ├── main.py             # App entry point & Table auto-generation
│   │   ├── database.py         # SQLAlchemy engine (PostgreSQL + Psycopg2)
│   │   ├── config.py           # Pydantic Settings (Validation & .env loading)
│   │   ├── inventory/
│   │   │   ├── models.py       # Route, Bus, Trip, and Seat entities
│   │   │   ├── schemas.py      # Pydantic models for Search & Layouts
│   │   │   └── router.py       # SRCH-01 (Trip Search) & SEAT-01 (Seat Map)
│   │   └── auth/
│   │       ├── models.py       # User & OTPVerification tables
│   │       ├── schemas.py      # OTP Request/Verify & TokenResponse
│   │       ├── service.py      # OTP Generation & Verification logic
│   │       └── router.py       # AUTH-01 (Passwordless OTP Endpoints)
├── .gitignore                  # Ignoring .venv, __pycache__, and .env
└── context.md                  # Project tracking (This file)
3. Tech Stack & Implementation Details
Language: Python 3.12+ (Running in .venv).

Framework: FastAPI.

Database: PostgreSQL 15 (via Docker).

ORM: SQLAlchemy with psycopg2-binary.

Configuration: Pydantic Settings V2 for strict environment variable enforcement.

4. Current Progress & State
Infrastructure: * Monorepo structure finalized.

Dockerized database is operational (ticket_booking_db).

App successfully connects to Postgres and auto-creates tables on startup.

Inventory Module: * SRCH-01: Search trips by origin/destination/date with available seat counts.

SEAT-01: Endpoint for trip-specific seat maps initialized.

Auth Module: * AUTH-01: Full OTP flow (Request -> Generate -> Store -> Verify) implemented.

Passworldless login structure ready for JWT integration.

5. Next Task
Finalize JWT (JSON Web Token) Generation. Now that OTP verification works, we need to replace the "mock_token_for_now" with a real, signed token so we can secure the booking endpoints.
