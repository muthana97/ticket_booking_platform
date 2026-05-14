📑 Project Context: Ticket Booking Platform (Master)
1. System Overview & Objectives
Goal: A high-concurrency, multi-provider marketplace for bus tickets.

Core Logic: Atomic seat management using PostgreSQL row-level locking (with_for_update) to prevent double-booking.

Primary Constraints: 100% reliability for seat holds and a 10-minute expiry window for pending payments.

2. Technical Stack (Live)
Backend: FastAPI (Python 3.12+) running via Uvicorn.

Database: PostgreSQL 15 running in a Docker container (ticket_booking_db).

ORM: SQLAlchemy with psycopg2-binary.

Authentication: Passwordless OTP (One-Time Password) via SMS.

3. Comprehensive File Manifest
This section allows a future assistant to understand the exact role of every existing file.

🏗️ Infrastructure & Config
backend/docker-compose.yml: Configures the PostgreSQL service, environment variables, and persistent data volumes.

backend/.env: Contains local secrets: DATABASE_URL, SECRET_KEY, and DEBUG mode.

backend/src/config.py: A Pydantic Settings class that loads and validates .env variables.

backend/src/database.py: Initializes the SQLAlchemy engine and defines the get_db session generator.

backend/src/main.py: The application entry point; includes all routers and executes Base.metadata.create_all to build tables on startup.

🚌 Inventory Module (src/inventory/)
models.py: Defines the relational schema for Route, Bus, Trip, and Seat.

schemas.py: Contains Pydantic models for data validation, specifically TripSearchResponse and BusLayoutResponse.

router.py: Handles SRCH-01 (Searching trips by origin/destination/date) and SEAT-01 (Fetching specific bus seat maps).

🔐 Auth Module (src/auth/)
models.py: Defines User and OTPVerification tables.

schemas.py: Defines structures for OTPRequest and TokenResponse.

service.py: Encapsulates logic for generating, hashing, and validating OTP codes.

router.py: Implements AUTH-01 endpoints: /request-otp and /verify-otp.

🎟️ Booking Module (src/booking/)
models.py: Defines Booking and Passenger entities.

service.py: Contains the "Hot Path" logic for atomic seat locking.

4. Current Operational State
Database: All 6 core tables are verified and active in the Docker container.

Web Server: Responding with {"status":"healthy"} at the root.

Documentation: Swagger UI is fully populated and functional at /docs.

Latest Logic Sync: The inventory/router.py is configured with path parameters for trip_id, and auth/router.py is ready to replace mock tokens with real JWTs.

5. Next Phase: Security & Data
JWT Implementation: Shift from mock strings to signed tokens in the Auth Service.

Data Seeding: Populate routes, buses, and trips to test the search end-to-end.

Booking Integration: Wire the booking/service.py into a router to allow users to reserve seats.

Assistant Note: If you are continuing this project, you can ask for the code of any file listed in the File Manifest above to see the current logic and implementation details.
