# Project Context: Ticket Booking Platform (Active Development)

## 1. System Overview & Objectives
* **Goal**: A high-concurrency, multi-provider marketplace for bus tickets featuring real-time seat locking and dual-path payment integration (Bank of Khartoum Direct API & Extended Billing Reference Windows).
* **Core Logic**: Atomic seat management using PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) to prevent double-booking. The system includes an automated "Reaper" lifecycle background task daemon synchronized to release expired seat maps across both checkout phases. Confirmed bookings update physical seat records to `"booked"`, shielding them from background sweeps permanently.

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
│       ├── booking/             # Atomic locking, Billing Intent, Settlement & Reaper logic
│       └── common/              # Shared utilities
4. Comprehensive File Manifest
backend/requirements.txt: Fully cataloged footprint locking fastapi, uvicorn, sqlalchemy, psycopg2-binary, and explicit pydantic-settings splits.
backend/src/booking/models.py: Contains Booking and Passenger models. Status fields support state-tracking vectors (payment_method, payment_status, billing_reference, bill_generated_at) and audit-trail structures (refund_amount, refund_status, refund_processed_at).
backend/src/booking/schemas.py: Comprehensive validation schemas processing BookingLockRequest, BookingResponse, BillingIntentRequest, BillingIntentResponse, PaymentSettlementRequest, BookingConfirmationResponse, and TripManifestResponse collections.
backend/src/booking/service.py: Core transaction engine handling atomic seat reservation (lock_seats), 30-minute billing reference generation (create_billing_intent), direct payment settlement verification (settle_direct_payment), and structured passenger extraction (compile_trip_manifest).
backend/src/booking/router.py: Secure route management enforcing strict JWT validation gates across /lock, /intent/billing, /settle/direct, and /trips/{trip_id}/manifest operators.
backend/src/booking/tasks.py: Upgraded background cleaner daemon utilizing safe python-naive UTC evaluations to batch-flush expired locks across both "pending" and "committed_pending" records.
5. Current Operational State
Identity (IAM): 100% Complete. Real JWT issuance and verification functional.
Inventory: 100% Complete. Database seeding and trip search logic functional.
Booking Engine: 100% Complete. Atomic locking verified via race-condition tests. Multi-path initialization schemas completely operational.
The Reaper Daemon: 100% Complete. Advanced dual-state tracking avoids zombie holds and preserves extended transactional windows.
Payment Integration (Phase 5): 100% Complete. Both Path A (Direct API Settlement Validation) and Path B (Billing Intent Mechanics) are fully built out, protected by row-level isolation (with_for_update), and safely verified.
Operational Reporting (Phase 6 Entry): 100% Complete. Secure manifest engine compiling structured passenger logs for provider clearance.
6. Next Steps (Priority Order)
Cancellation & Refund Audit Trail Engine (CAN-03): Implement service methods, payload schemas, and validation routes to process user cancellation intents, release seats instantly back to available status, and calculate exact multi-tier refund thresholds based on departure horizons.
Frontend Real-Time Sync: Link backend actions to client sockets or poll protocols to handle dynamic seat map updates across customer and provider screens.
