Project Context: Ticket Booking Core
1. System Overview
A real-time, multi-provider marketplace for bus ticket booking.

Core Goal: High-concurrency seat management and dual-path payment integration (BoK & Billing Reference).

Architecture: Monolithic FastAPI with Domain-Driven Design (DDD).

Primary Constraints: 100% reliability for double-booking prevention (Atomic Transactions) and 99% system uptime.

2. Directory Structure Status
The current backend structure is as follows:

Plaintext
ticket_booking_core/
├── src/
│   ├── main.py             
│   ├── database.py         # SQLAlchemy engine & session configuration (Standard)
│   ├── config.py           # Pydantic Settings & .env management
│   ├── inventory/
│   │   └── models.py       # Route, Bus, Trip, and Seat entities
│   ├── booking/
│   │   ├── models.py       # Booking and Passenger entities
│   │   └── service.py      # Atomic seat-locking logic (with_for_update)
│   ├── auth/               
│   ├── finance/            
│   ├── admin/              
│   └── common/             
├── .env                    # Database credentials & Secrets
└── requirements.txt        
3. Tech Stack & Implementation Details
Backend: FastAPI (Python 3.10+).

Database: PostgreSQL via SQLAlchemy ORM.

Concurrency Control: Implemented via Row-Level Locking (with_for_update) in the Booking Service to satisfy NFR-05.

Data Handling: Flexible seat layouts stored as JSON in the Bus model to accommodate various provider configurations.

4. Current Progress & State
Foundation: Configuration management and database session handling are fully operational.

Inventory Module: Models for Routes, Buses, and Trips are defined. Seats are linked to Trips to allow granular availability tracking.

Booking Module: Initialized with models for Bookings and Passengers (Manifesto support).

Logic: The "Hot Path" for locking seats is implemented in src/booking/service.py.

5. Next Task
Build the FastAPI Routes for the Customer side, specifically Trip Search (SRCH-01) and Seat Selection (SEAT-01), to begin testing the end-to-end flow.
