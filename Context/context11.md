# Project Context: Ticket Booking Platform (Active Development)

## 1. System Overview & Objectives
* **Goal**: A high-concurrency, multi-provider marketplace for bus tickets featuring real-time seat locking and dual-path payment integration (Bank of Khartoum Direct API & Extended Billing Reference Windows).
* **Core Logic**: Atomic seat management using PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) to prevent double-booking. The system includes an automated "Reaper" lifecycle background task daemon synchronized to release expired seat maps across both checkout phases.

## 2. Technical Stack (Live)
| Layer | Technology |
| :--- | :--- |
| **Backend** | FastAPI (Python 3.14) running via Uvicorn |
| **Database** | PostgreSQL 15 (Docker: `ticket_booking_db`) |
| **ORM** | SQLAlchemy with `psycopg2-binary` |
| **Security** | JWT signed via `python-jose`; OTP-based authentication |
| **Concurrency** | Row-level locking (`with_for_update`) in booking service |
| **Worker** | Async lifespan background task (The Reaper Dual-State Engine) |

## 3. Directory Structure (Monorepo)
```plaintext
ticket_booking_platform/
├── backend/
│   ├── .env                     # DATABASE_URL, SECRET_KEY, JWT_ALGORITHM
│   ├── docker-compose.yml       # PostgreSQL 15 container config
│   ├── requirements.txt         # Project dependency footprint (Pydantic v2 split ready)
│   └── src/
│       ├── main.py              # App entry point & background task orchestration
│       ├── config.py            # Settings loader (JWT & Lock constraints)
│       ├── database.py          # SQLAlchemy engine & session generator
│       ├── auth/                # OTP & JWT logic
│       ├── inventory/           # Trip search & seat map logic
│       ├── booking/             # Atomic locking, Billing Intent, & Reaper logic
│       └── common/              # Shared utilities
4. Comprehensive File Manifest
backend/requirements.txt: Fully cataloged footprint locking fastapi, uvicorn, sqlalchemy, psycopg2-binary, and explicit pydantic-settings splits.
backend/src/booking/models.py: Phase 5 status structure containing database vectors (payment_method, payment_status, billing_reference, bill_generated_at) and non-editable audit trail parameters (refund_amount, refund_status, refund_processed_at).
backend/src/booking/schemas.py: Comprehensive Pydantic schema validation layer processing BookingLockRequest, BookingResponse, BillingIntentRequest, BillingIntentResponse, and TripManifestResponse collections.
backend/src/booking/service.py: Master logic layer handling high-concurrency seat reservation initialization (lock_seats), row-locked 30-minute billing reference generation (create_billing_intent), and transactional passenger extraction (compile_trip_manifest).
backend/src/booking/router.py: Secure route management enforcing strict JWT validation gates across /lock, /intent/billing, and /trips/{trip_id}/manifest operators.
backend/src/booking/tasks.py: Refactored Reaper background daemon utilizing safe python-naive UTC evaluations to batch-flush expired locks across both "pending" and "committed_pending" records.
5. Current Operational State
Identity (IAM): 100% Complete. Real JWT issuance and verification functional.
Inventory: 100% Complete. Database seeding and trip search logic functional.
Booking Engine: 100% Complete. Concurrency engine verified. Multi-path initialization schemas completely operational.
The Reaper Daemon: 100% Complete. Advanced dual-state tracking avoids zombie holds and preserves extended transactional windows.
Operational Reporting: 100% Complete. Secure manifest engine compiling structured passenger logs for provider clearance.
6. Next Steps (Priority Order)
Path A API Settlement / Direct Payment Validation: Build out the transaction settlement handler route to parse final incoming successful direct payments, advance booking state to confirmed, switch payment to paid, and lock the physical seat array permanently from the Reaper.
Cancellation & Refund Audit Trail Engine (CAN-03): Implement validation routes to process user cancellation intents and calculate exact multi-tier refund thresholds based on departure horizons into refund_amount tracks.
