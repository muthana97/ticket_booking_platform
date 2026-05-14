Project Context: Ticket Booking Platform
1. System Overview
A real-time, multi-provider marketplace for bus ticket booking.

Core Goal: High-concurrency seat management and dual-path payment integration (BoK & Billing Reference).

Architecture: Monorepo (FastAPI Backend, placeholders for Frontend/Mobile).

Primary Constraints: 100% reliability for double-booking prevention (Atomic Transactions) and 99% system uptime.

2. Directory Structure Status
The project has been restructured into a Monorepo to support future scale:

Plaintext
ticket_booking_platform/
├── backend/
│   ├── src/
│   │   ├── main.py             # Entry point; connects routers & creates tables
│   │   ├── database.py         # SQLAlchemy configuration
│   │   ├── config.py           # Pydantic Settings
│   │   ├── inventory/
│   │   │   ├── models.py       # Route, Bus, Trip, and Seat entities
│   │   │   ├── schemas.py      # Pydantic models for Search/Layout validation
│   │   │   └── router.py       # API Endpoints for SRCH-01 and SEAT-01
│   │   └── booking/
│   │       ├── models.py       # Booking and Passenger entities
│   │       └── service.py      # Atomic seat-locking logic (with_for_update)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                   # (Planned)
├── mobile/                     # (Planned)
├── .env                        # Root-level configuration
└── context.md                  # Project tracking
3. Tech Stack & Implementation Details
Backend: FastAPI (Python 3.10+).

Database: PostgreSQL via SQLAlchemy ORM.

Concurrency: Row-Level Locking (with_for_update) in the Booking Service (NFR-05).

API Standards: Pydantic schemas enforced for all requests/responses to ensure data integrity.

4. Current Progress & State
Infrastructure: Successfully migrated to a Monorepo structure and initialized Git.

Version Control: Repository muthana97/ticket_booking_platform is live on GitHub.

Inventory Module: Fully implemented.

SRCH-01: Trip search logic by origin, destination, and date is complete.

SEAT-01: Seat map retrieval logic (mapping JSON layouts to live seat status) is complete.

Database Logic: Base.metadata.create_all is wired in main.py for automated table generation.

5. Next Task
Implement the Authentication Module (AUTH-01). This includes setting up the OTP (One-Time Password) generation and validation logic for customer login, ensuring we have a secure way to associate bookings with users.
