Project Context: Ticket Booking Platform
1. System Overview
Goal: Multi-provider marketplace for bus tickets with real-time seat locking.

Architecture: Monorepo. Backend is FastAPI (Python 3.12+).

Service Logic: Atomic transactions to prevent double-booking.

2. Technical Stack
Database: PostgreSQL 15 (Dockerized).

Backend: FastAPI + SQLAlchemy (using psycopg2-binary).

Config: Pydantic Settings V2 for .env management.

Environment: Virtual environment (.venv) located in backend/.

3. Current File State (Synchronized)
backend/.env: Contains DATABASE_URL (Postgres), SECRET_KEY, and DEBUG=True.

backend/docker-compose.yml: Defines the db service (Postgres) with matching credentials.

backend/src/main.py: Includes both inventory_router and auth_router. Auto-generates tables on startup via Base.metadata.create_all.

backend/src/inventory/router.py:

SRCH-01: Full logic for searching trips by origin, destination, and date.

SEAT-01: Skeleton endpoint @router.get("/{trip_id}/seats") ready for path parameter testing.

backend/src/auth/router.py: Full logic for request-otp and verify-otp (mock JWT return).

4. Immediate Action Item
Docker Initialization: Launch the PostgreSQL container and confirm the database is accepting connections.
