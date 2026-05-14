Project Context: Ticket Booking Platform (Final)

1. System Overview & Objectives

Goal: A high-concurrency, multi-provider marketplace for bus tickets with real-time seat locking and dual-path payment integration (BoK & Billing Reference).

Core Logic: Atomic seat management using PostgreSQL row-level locking (SELECT ... FOR UPDATE) to prevent double‑booking – 100% reliability for seat holds.

Primary Constraints:

Double‑booking prevention: 100% (atomic transactions)
System uptime: 99%
Pending payment expiry: 10 minutes (seats released automatically)
Architecture: Monorepo – Backend (FastAPI), plus placeholders for Frontend & Mobile.

2. Technical Stack (Live)

Layer	Technology
Backend	FastAPI (Python 3.12+) running via Uvicorn
Database	PostgreSQL 15 (Docker container: ticket_booking_db)
ORM	SQLAlchemy with psycopg2-binary
Authentication	Passwordless OTP (One‑Time Password) via SMS – JWT pending
Configuration	Pydantic Settings V2 with .env
Concurrency Control	Row‑level locking (with_for_update) in booking service
Seat Layout	Flexible JSON storage in Bus model (accommodates multiple providers)
3. Directory Structure (Monorepo)

text
ticket_booking_platform/
├── backend/
│   ├── .env                     # DATABASE_URL, SECRET_KEY, DEBUG
│   ├── .venv/                   # Python 3.12+ virtual environment
│   ├── docker-compose.yml       # PostgreSQL 15 container config
│   ├── requirements.txt
│   ├── Dockerfile               # (for future deployment)
│   └── src/
│       ├── main.py              # App entry point, router registration, table creation
│       ├── config.py            # Pydantic settings loader & validator
│       ├── database.py          # SQLAlchemy engine & get_db session generator
│       ├── inventory/
│       │   ├── models.py        # Route, Bus, Trip, Seat entities
│       │   ├── schemas.py       # Pydantic models for search & layout responses
│       │   └── router.py        # SRCH-01 (trip search) & SEAT-01 (seat map)
│       ├── auth/
│       │   ├── models.py        # User & OTPVerification tables
│       │   ├── schemas.py       # OTP request/verify + TokenResponse
│       │   ├── service.py       # OTP generation, hashing, validation logic
│       │   └── router.py        # AUTH-01 endpoints: /request-otp, /verify-otp (mock JWT)
│       ├── booking/
│       │   ├── models.py        # Booking and Passenger entities
│       │   └── service.py       # Atomic seat‑locking logic (with_for_update)
│       └── common/              # (reserved for shared utilities)
├── frontend/                    # (planned – placeholder)
├── mobile/                      # (planned – placeholder)
├── .gitignore
└── context.md                   # This file
4. Comprehensive File Manifest (with exact roles)

🏗️ Infrastructure & Config

backend/docker-compose.yml – PostgreSQL service definition, credentials, persistent volume.
backend/.env – Local secrets: DATABASE_URL, SECRET_KEY, DEBUG=True.
backend/src/config.py – Pydantic Settings class, validates and loads environment variables.
backend/src/database.py – SQLAlchemy engine setup, get_db dependency for sessions.
backend/src/main.py – FastAPI app, includes inventory_router and auth_router, calls Base.metadata.create_all on startup to auto‑build tables.
🚌 Inventory Module (src/inventory/)

models.py – Relational schema: Route, Bus (with seat_layout: JSON), Trip, Seat (linked to trip).
schemas.py – Pydantic models: TripSearchResponse, BusLayoutResponse.
router.py – Implements:
SRCH-01: GET /trips/search?origin=&destination=&date= – returns trips with available seat counts.
SEAT-01: GET /trips/{trip_id}/seats – returns seat map for a specific trip, merging JSON layout with live booking status.
🔐 Auth Module (src/auth/)

models.py – User (phone number, etc.) and OTPVerification (code hash, expiry, attempts).
schemas.py – OTPRequest, OTPVerify, TokenResponse.
service.py – Generate 6‑digit OTP, hash with secret pepper, store with 5‑min expiry, validate with rate‑limit protection.
router.py – /request-otp (sends SMS – currently logs to console) and /verify-otp (returns TokenResponse with mock JWT – placeholder for real signing).
🎟️ Booking Module (src/booking/)

models.py – Booking (status: pending/confirmed/cancelled, expiry timestamp) and Passenger (name, ID, seat number).
service.py – lock_seats(trip_id, seat_numbers, booking_id) – uses with_for_update() inside a transaction to atomically mark seats as held. Raises exception if any seat already locked/confirmed.
5. Current Operational State (Verified)

Component	Status
Database	All 6 core tables (routes, buses, trips, seats, users, otp_verifications, bookings, passengers) exist in Docker container.
Web Server	Running, root endpoint returns {"status":"healthy"}.
API Documentation	Swagger UI fully populated at /docs.
Inventory Router	Endpoints SRCH-01 and SEAT-01 functional (path parameters tested).
Auth Router	OTP flow works end‑to‑end; returns a mock token (real JWT pending).
Booking Service	Atomic locking logic implemented but not yet exposed via a router – seats can be locked programmatically but no HTTP endpoint exists.
6. What Is Missing / Next Steps (Priority Order)

JWT Implementation – Replace mock token in auth/router.py with a real signed JWT (python-jose or PyJWT) using the SECRET_KEY.
Data Seeding – Populate routes, buses, trips, and seats to test search and seat selection end‑to‑end.
Booking Router – Create src/booking/router.py with endpoints:
POST /bookings/lock – calls service.lock_seats(), returns booking ID and expiry.
POST /bookings/confirm/{booking_id} – finalises payment (integration with BoK/Billing Reference).
Payment Integration – Dual‑path (BoK & Billing Reference) – design not yet started.
Expiry Job – Background task or cron to release seats after 10 minutes (pending bookings).
7. Important Constraints & Design Decisions (Preserved from earlier contexts)

Row‑level locking is the only accepted concurrency mechanism (NFR‑05). Pessimistic locking ensures no double‑booking.
Seat layouts are stored as JSON in the Bus model – allows each provider to define their own schema (e.g., 2x2, 2x1, sleeper).
Monorepo with frontend/ and mobile/ placeholders – future expansion anticipated.
Environment isolation – .venv inside backend/, Docker for database only.
Automatic table creation – Base.metadata.create_all in main.py (suitable for development; production would use migrations).
8. How to Use This Document

If you are continuing this project, you can request the code of any file listed in the File Manifest above. All logic is aligned with the current state described here. Any future assistant should treat this document as the single source of truth.
