
# Ticket Booking Platform – Complete Requirements Document

## System Overview

A real-time, multi-provider marketplace for bus ticket booking. The platform connects customers with bus companies (providers) and enables the platform owner (admin) to manage operations, commissions, and reporting.

| Role | Primary Functions |
| :--- | :--- |
| **Customer** | Search trips, select seats, book tickets, pay, view tickets |
| **Provider** | Manage trips, define seat layouts, book seats (walk-in/online), enter passenger details, Offline Manifesto Access |
| **Admin** | Manage providers/routes, set commissions, run campaigns, view reports, audit dispute resolution |

---

## Part 1: Customer Side

### 1.1 Authentication

| ID | Requirement |
| :--- | :--- |
| AUTH-01 | Customer must log in using OTP (One-Time Password) sent to their registered phone number. |
| AUTH-02 | Session must persist until explicit logout or token expiry. |

### 1.2 Trip Search

| ID | Requirement |
| :--- | :--- |
| SRCH-01 | Customer must search trips using Origin, Destination, and Travel Date. |
| SRCH-02 | Search results must display: trip ID, provider name, departure time, arrival time, price, available seats. |
| SRCH-03 | Search response time ≤ 2 seconds. |

### 1.3 Seat Selection

| ID | Requirement |
| :--- | :--- |
| SEAT-01 | Customer must select specific seats using a visual seat map/grid (e.g., 14A, 14B). |
| SEAT-02 | System must prevent double booking of the same seat using database atomic transactions. |
| SEAT-03 | Seat availability must be real-time synchronized across customer, provider, and admin panels. |
| SEAT-04 | Selected seats must be locked for 10–15 minutes during checkout. If payment not completed, seat auto-releases. |

### 1.4 Booking Flow

| ID | Requirement |
| :--- | :--- |
| BOOK-01 | Customer completes booking in this sequence: 1. Select trip, 2. Select seat(s), 3. Enter passenger details, 4. Proceed to payment, 5. Confirm booking |
| BOOK-02 | System must generate a unique booking ID for each confirmed booking. |
| BOOK-03 | System must store booking status: pending, confirmed, cancelled, expired. |
| BOOK-04 | State persistence on internet drop: If connection fails during booking, the system must remember the user's progress and selected seat for at least 5 minutes. |

### 1.5 Passenger Information (Manifesto)

| ID | Requirement |
| :--- | :--- |
| MAN-01 | For each passenger, customer must provide: Full name, Phone number, National ID (if required for legal compliance). |
| MAN-02 | System must automatically generate a manifest (passenger list) for each trip. |
| MAN-03 | Manifest must be accessible to providers and admin for security clearance. |

### 1.6 Payment

| ID | Requirement |
| :--- | :--- |
| PAY-01 | Customer must initiate payment after entering passenger details. |
| PAY-02 | System must handle payment success, failure, and delay scenarios. |
| PAY-03 | System must support reconciliation of payments against booking IDs (automated or semi-automated). |
| PAY-04 | **Dual-path payment integration:** <br>• **Path A (Direct):** Integration with Bank of Khartoum API <br>• **Path B (Billing):** Reference-number system where user "commits to pay", a bill number is generated, and the user is expected to complete payment within 30 minutes. |

### 1.7 Ticket Management

| ID | Requirement |
| :--- | :--- |
| TKT-01 | Customer must view all active tickets (upcoming trips). |
| TKT-02 | Customer must view all past tickets (completed trips). |
| TKT-03 | Customer must view cancelled tickets with status. |
| TKT-04 | Each ticket displays: trip details, seat number(s), passenger name(s), booking ID, QR code. |

### 1.8 Booking Cancellation

| ID | Requirement |
| :--- | :--- |
| CAN-01 | Customer may cancel a booking before a defined cutoff (e.g., 2 hours before departure). |
| CAN-02 | Canceled seats must be immediately released back to inventory. |
| CAN-03 | When a cancellation is processed, the system must record refund_amount (if applicable), refund_status (pending/processed/void), and refund_processed_at timestamp. |

### 1.9 Support

| ID | Requirement |
| :--- | :--- |
| SUP-01 | The system must display a visible "Contact Support" button/link in all interfaces (customer app, provider panel). |
| SUP-02 | Tapping/clicking "Contact Support" must display: phone number, email address, and WhatsApp link (if applicable). |
| SUP-03 | Customer and provider messages sent via the platform must be logged with timestamp and user ID for audit purposes. |

---

## Part 2: Provider Side

### 2.1 Authentication

| ID | Requirement |
| :--- | :--- |
| P-AUTH-01 | Provider logs in using phone number + OTP. |
| P-AUTH-02 | Session persists until logout or expiry. |

### 2.2 Trip Management

| ID | Requirement |
| :--- | :--- |
| P-TRIP-01 | Provider must create a new trip via "Manage Trips +". |
| P-TRIP-02 | Provider must view, edit, and delete existing trips. |
| P-TRIP-03 | Trip creation includes: origin, destination, departure time, price, bus ID, total seats. |
| P-TRIP-04 | Provider must be able to define seat layouts per bus (e.g., 2x2 grid, aisle configuration, total seat count). |

### 2.3 Route & Schedule Display

| ID | Requirement |
| :--- | :--- |
| P-ROUTE-01 | Provider sees route list as origin → destination pairs. |
| P-ROUTE-02 | Provider must filter routes (e.g., by origin). |
| P-ROUTE-03 | Provider must insert a new schedule for an existing route. |

### 2.4 Seat Selection & Booking (Provider-Initiated)

| ID | Requirement |
| :--- | :--- |
| P-SEAT-01 | Provider must select specific seats for walk-in or phone customers. |
| P-SEAT-02 | Seat map indicates available vs booked seats, based on the defined layout per bus. |
| P-SEAT-03 | System prevents double booking using atomic transactions. |
| P-SEAT-04 | Seat selection updates availability in real time across all interfaces. |

### 2.5 Passenger Details Entry

| ID | Requirement |
| :--- | :--- |
| P-PAX-01 | For each passenger, provider enters: Name, Phone number. |
| P-PAX-02 | National ID field included (if required). |
| P-PAX-03 | Provider can enter details for multiple passengers. |

### 2.6 Pricing & Seat Count

| ID | Requirement |
| :--- | :--- |
| P-PRICE-01 | For each trip, provider sees: Price, Number of available seats. |
| P-PRICE-02 | Price and seat count reflect real-time state. |

### 2.7 Booking Confirmation

| ID | Requirement |
| :--- | :--- |
| P-CONF-01 | Provider clicks "Confirm & Pay" to finalize booking. |
| P-CONF-02 | System displays "TICKET BOOKED" confirmation. |
| P-CONF-03 | Booking is added to trip manifesto. |

### 2.8 Payment Handling (Provider-Initiated)

| ID | Requirement |
| :--- | :--- |
| P-PAY-01 | Provider chooses: • Allow payment through platform portal (redirect to payment page) • Mark as cash payment (walk-in customer) |
| P-PAY-02 | Platform payment uses same dual-path integration (Bank of Khartoum or billing reference). |
| P-PAY-03 | Cash bookings are confirmed immediately; commission is still tracked. |

### 2.9 Additional Provider Requirements

| ID | Requirement |
| :--- | :--- |
| P-EXT-01 | Provider must list buses and routes. |
| P-EXT-02 | Provider must set pricing per route. |
| P-EXT-03 | Provider must manage seat inventory (e.g., block seats). |
| P-EXT-04 | Provider books tickets for online users (app) and walk-in customers (panel). |
| P-EXT-05 | Provider must view manifesto & print (passenger list) for each trip. |
| P-EXT-06 | The provider must be able to generate and print a final manifesto for any trip before departure. |

### 2.10 Support

| ID | Requirement |
| :--- | :--- |
| P-SUP-01 | The system must display a visible "Contact Support" button/link in all interfaces. |
| P-SUP-02 | Tapping/clicking "Contact Support" must display: phone number, email address, and WhatsApp link (if applicable). |
| P-SUP-03 | Customer and provider messages sent via the platform must be logged with timestamp and user ID for audit purposes. |

---

## Part 3: Admin Panel

### 3.1 Admin Authentication

| ID | Requirement |
| :--- | :--- |
| A-ADM-01 | Admin logs in using email/username + strong password. |
| A-ADM-02 | Admin session has role-based access control (RBAC). |
| A-ADM-03 | Admin accounts created by super-admin or system bootstrap. |

### 3.2 Provider Management

| ID | Requirement |
| :--- | :--- |
| A-PROV-01 | Admin adds a new provider (bus company). |
| A-PROV-02 | Admin views all providers with details: name, contact, phone, email, status. |
| A-PROV-03 | Admin edits provider information. |
| A-PROV-04 | Admin suspends or reactivates a provider. |
| A-PROV-05 | Suspended provider's trips do not appear in customer search. |
| A-PROV-06 | Admin soft-deletes a provider (preserve history). |

### 3.3 Route Management

| ID | Requirement |
| :--- | :--- |
| A-RTE-01 | Admin views all routes across providers. |
| A-RTE-02 | Admin adds a new route (origin, destination, distance, duration). |
| A-RTE-03 | Admin edits or deletes a route. |
| A-RTE-04 | Admin approves or rejects provider-submitted routes. |
| A-RTE-05 | Admin views trips associated with a route. |

### 3.4 Commission Management

| ID | Requirement |
| :--- | :--- |
| A-COMM-01 | Admin sets default global commission rate (percentage). |
| A-COMM-02 | Admin sets provider-specific commission rates (overrides global). |
| A-COMM-03 | Admin sets route-specific commission rates (overrides provider/global). |
| A-COMM-04 | Commission rates support percentage values. |
| A-COMM-05 | Admin views commission earned per provider, route, and period. |
| A-COMM-06 | Commission calculated automatically on each confirmed booking. |

### 3.5 Campaign & Discount Management

| ID | Requirement |
| :--- | :--- |
| A-CAMP-01 | Admin creates campaign with: name, discount type (percentage/fixed), value, start/end dates. |
| A-CAMP-02 | Admin applies campaign to: all routes, specific providers, specific routes. |
| A-CAMP-03 | Admin sets maximum discount amount or minimum booking value. |
| A-CAMP-04 | Admin edits, pauses, or deletes campaigns. |
| A-CAMP-05 | System applies best available discount automatically at checkout. |
| A-CAMP-06 | Admin views campaign performance (bookings, discount given). |
| A-CAMP-07 | Admin configures campaign where: platform reduces commission (e.g., 3% → 1%), 2% difference becomes customer discount. |
| A-CAMP-08 | Admin sees net platform revenue per booking after campaign adjustments. |

### 3.6 Financial Reports

| ID | Requirement |
| :--- | :--- |
| A-FIN-01 | Admin dashboard shows: total bookings (today/week/month), total revenue, total commission, total provider payouts. |
| A-FIN-02 | Admin generates commission report with filters: date range, provider, route. |
| A-FIN-03 | Commission report shows per booking: booking ID, customer, trip, ticket price, commission rate, commission amount, campaign applied. |
| A-FIN-04 | Admin exports reports as CSV or Excel. |
| A-FIN-05 | Admin views payment reconciliation status per provider. |
| A-FIN-06 | Admin sees outstanding balance owed to each provider. |

### 3.7 Operational Reports

| ID | Requirement |
| :--- | :--- |
| A-OP-01 | Admin views total bookings per day/week/month (chart). |
| A-OP-02 | Admin views seat occupancy rate per trip, route, provider. |
| A-OP-03 | Admin views most popular routes (by bookings). |
| A-OP-04 | Admin views cancellation rate per provider/route. |
| A-OP-05 | Admin views manifesto for any trip. |
| A-OP-06 | Admin searches bookings by booking ID, customer phone, or ticket number. |

### 3.8 System Monitoring

| ID | Requirement |
| :--- | :--- |
| A-MON-01 | Admin views recent system logs (bookings, payments, errors). |
| A-MON-02 | Admin views basic system health (API status, DB connectivity). |
| A-MON-03 | Admin receives alerts for critical failures (payment API down, double booking). |
| A-MON-04 | Audit logs for dispute resolution: Every booking, cancellation, and payment attempt must be logged with timestamp, actor, and affected booking ID. Logs must be non-editable and exportable. |

### 3.9 Provider Approval Workflow

| ID | Requirement |
| :--- | :--- |
| A-APPR-01 | New provider registrations require admin approval before listing trips. |
| A-APPR-02 | Admin approves or rejects with reason. |

---

## Part 4: Non-Functional Requirements (All Interfaces)

| ID | Requirement | Target |
| :--- | :--- | :--- |
| NFR-01 | API response time (excluding search) | ≤ 500 ms |
| NFR-02 | Database query latency | ≤ 100 ms |
| NFR-03 | Search response time | ≤ 2 seconds |
| NFR-04 | Real-time seat sync (provider ↔ customer) | ≤ 1 second |
| NFR-05 | Double booking prevention | 100% reliability (atomic transactions) |
| NFR-06 | System uptime | 99% |
| NFR-07 | Personal data security (phone, ID, name) | Encrypted at rest and in transit |
| NFR-08 | OTP handling | Secure, rate-limited |
| NFR-09 | Admin report generation (up to 10k bookings) | ≤ 10 seconds |
| NFR-10 | Admin panel access | Internal/VPN or MFA for production |
| NFR-11 | Admin actions | Full audit logging |
| NFR-12 | State persistence on connection drop | User progress + seat lock retained for 5 minutes |
| NFR-13 | Offline manifesto access | Provider app caches manifest for checkpoint access without internet |
| NFR-14 | API rate limits | Guest: 10/min, Auth users/providers: 100/min, Admin: 200/min |
| NFR-15 | Frontend language support | English and Arabic (RTL). Language switching without page reload. |

---

## Part 5: Data Entities (Proposed/Non-Compulsory)

| Entity | Key Fields |
| :--- | :--- |
| **Customer** | id, phone_number, name (optional), created_at |
| **Provider** | id, name, contact_name, phone, email, status, created_at |
| **Bus** | id, provider_id, seat_layout_config (JSON), total_seats |
| **Route** | id, origin, destination, distance, duration, status |
| **Trip** | id, provider_id, bus_id, route_id, departure_time, price |
| **Seat** | id, trip_id, seat_number, status (available/locked/booked) |
| **Booking** | id, customer_id, trip_id, seat_ids, status, created_at, expires_at, progress_state, refund_amount, refund_status, refund_processed_at |
| **Passenger** | id, booking_id, name, phone, national_id |
| **Ticket** | id, booking_id, ticket_number, qr_code, status |
| **CommissionRule** | id, provider_id (nullable), route_id (nullable), rate (%), priority |
| **Campaign** | id, name, type, value, start_date, end_date, applicable_providers, applicable_routes |
| **BookingLog** | id, booking_id, customer_id, provider_id, route_id, ticket_price, commission_earned, campaign_id |
| **AuditLog** | id, timestamp, actor_id, actor_type, action, booking_id, details (JSON) |
| **AdminUser** | id, email, password_hash, role, last_login |

---

## Part 6: System Integration Requirements

| ID | Requirement |
| :--- | :--- |
| SYS-01 | **Dual-path payment integration:** Path A: Bank of Khartoum API (direct); Path B: Billing reference number system with confirmation window and timer. |
| SYS-02 | OTP delivery via SMS gateway. |
| SYS-03 | Real-time seat synchronization mechanism (e.g., Redis locks, database atomic transactions, or WebSockets). |
| SYS-04 | Payment reconciliation: Automated matching of payment confirmations to booking IDs. |
| SYS-05 | Push notifications for customers and providers (e.g., booking confirmation, payment status, seat lock expiry reminders). |

---

## Part 7: Tech-Stack (Optional)

| ID | Constraint |
| :--- | :--- |
| ENG-01 | Backend: FastAPI (suggested) |
| ENG-02 | Database: PostgreSQL |
| ENG-03 | ORM: SQLAlchemy |
| ENG-04 | Frontend: React or equivalent |
| ENG-05 | Concurrency: Database atomic transactions (e.g., SELECT FOR UPDATE, row-level locking) |
| ENG-06 | Scalable architecture: Domain-driven design to allow future addition of other booking domains (e.g., sports pitches, events). |

---

## Part 8: Business Logic Examples

### Commission Calculation Example

| Input | Value |
| :--- | :--- |
| Ticket price | 10,000 SDG |
| Commission rate | 3% |

| Output | Amount |
| :--- | :--- |
| Customer pays | 10,000 SDG |
| Platform earns (commission) | 300 SDG |
| Provider receives | 9,700 SDG |

### Campaign + Commission Example

| Scenario | Value |
| :--- | :--- |
| Normal commission | 3% |
| Campaign reduces commission to | 1% |
| Difference (2%) becomes | Customer discount |

**Result:** Customer pays less, provider still receives 9,700 SDG, platform earns 100 SDG instead of 300 SDG.

---

## Part 9: Error Handling Requirements

| ID | Requirement |
| :--- | :--- |
| ERR-01 | All API failures must return a meaningful, user-friendly error message in English/Arabic based on user's language setting. |
| ERR-02 | Payment failures (Path A): Display clear reason (e.g., "Insufficient funds") and allow retry without re-entering passenger details. |
| ERR-03 | Payment timeout (>30 seconds): Display "Payment is taking longer than expected. You will receive confirmation via SMS/notification within 10 minutes. Do not retry payment." |
| ERR-04 | OTP delivery failure: User can request new OTP after 30 seconds. Max 3 attempts per phone number per hour. |
| ERR-05 | Seat lock failure (e.g., race condition): Retry up to 3 times within 2 seconds. If all fail, display "Selected seats no longer available. Please refresh and try again." |
| ERR-06 | Search timeout (>2 seconds): Display partial results with warning "Some results may be incomplete. Please try again." |
| ERR-07 | BoK bill generation failure (Path B): Display "Payment bill could not be generated. Please try another payment method or contact support." and release seat lock immediately. |
| ERR-08 | Network connection loss during booking: Display persistent banner "Connection lost. Attempting to reconnect..." and auto-retry for up to 5 minutes. |
| ERR-09 | All errors must be logged to AuditLog with timestamp, user ID, error type, endpoint/action, and technical details. |
| ERR-10 | Critical errors (payment API down, database unreachable, double booking) must trigger admin alert per A-MON-03. |

