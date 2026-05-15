context.md
Project Context: Ticket Booking Core
1. System Overview
A real-time, multi-provider marketplace for bus ticket booking.

Core Goal: High-concurrency seat management and dual-path payment integration (BoK & Billing Reference).

Architecture: Monolithic FastAPI with Domain-Driven Design (DDD).

Primary Constraints: 100% reliability for double-booking prevention (Atomic Transactions) and 99% system uptime.

2. Directory Structure Status
The following structure has been initialized via bash:

Plaintext
ticket_booking_core/
├── docker/                 # Containerization configs
├── scripts/                # Utility scripts
├── src/
│   ├── main.py             # Entry point
│   ├── database.py         # SQLAlchemy & Engine setup
│   ├── config.py           # Environment variables (Pydantic)
│   ├── auth/               # OTP & RBAC
│   ├── inventory/          # Trips, Buses, Routes
│   ├── booking/            # Seat locking & Manifests
│   ├── finance/            # Commissions & Payments
│   ├── admin/              # Reporting & Campaigns
│   └── common/             # Shared utils & middleware
├── tests/                  # Pytest suite
├── .env                    # Secrets (Not in Git)
├── Dockerfile              # System image
└── requirements.txt        # Dependencies (FastAPI, SQLAlchemy, etc.)
3. Tech Stack Requirements
Backend: FastAPI (Python).

Database: PostgreSQL with SQLAlchemy ORM.

Concurrency: Database-level atomic transactions (SELECT FOR UPDATE).

Communication: English and Arabic (RTL) support for errors/UI.

4. Current Progress & State
[Session 1]: Directory structure initialized. Project modules defined based on the requirements.v2.md.

Next Task: Build the foundation—database.py, config.py, and the initial SQLAlchemy models for Buses and Seats.
