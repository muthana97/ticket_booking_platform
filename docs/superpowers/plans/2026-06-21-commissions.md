# Commission System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three-tier commission system specified in `docs/superpowers/specs/2026-06-21-commissions-design.md` — global default + per-provider, per-(provider+route), per-trip overrides — with an immutable snapshot at booking confirmation and an admin Settings hub reachable from a gear icon.

**Architecture:** Backend gets a new `finance` module (models + schemas + service + router) whose endpoints are mounted under `/admin/commissions`. The existing `confirm_payment` helper in `admin/service.py` is the single hook that calls `finance.service.snapshot_commission`. Frontend gets a new `admin-settings` screen with a section-list layout, reached from a gear icon in the topbar.

**Tech Stack:** FastAPI 0.136 · SQLAlchemy 2.0 · Pydantic 2 · Postgres 15 (Render) / SQLite (tests) · vanilla JS single-page `frontend/index.html`. Tests use **pytest + sqlite in-memory** (pytest is not currently in the repo — Task 1 adds it).

---

## File map

**Backend — new files:**
- `backend/src/finance/models.py` — `CommissionRule` ORM model
- `backend/src/finance/schemas.py` — `RuleOut`, `GlobalUpsertIn`, `OverrideCreateIn`, `OverrideUpdateIn`, `CommissionsReadResponse`
- `backend/src/finance/service.py` — `resolve_rule`, `snapshot_commission`, `list_overrides`, `upsert_global`, `create_override`, `update_override`, `delete_override`
- `backend/src/finance/router.py` — admin-gated routes mounted at `/admin/commissions`
- `backend/tests/__init__.py` — empty marker
- `backend/tests/conftest.py` — pytest fixtures (in-memory SQLite engine + session + admin user fixture)
- `backend/tests/finance/__init__.py` — empty
- `backend/tests/finance/test_resolve_rule.py`
- `backend/tests/finance/test_snapshot.py`
- `backend/tests/finance/test_admin_commissions_api.py`
- `backend/tests/finance/test_provider_booking_visibility.py`
- `backend/tests/booking/__init__.py` — empty
- `backend/tests/booking/test_confirm_path_snapshots_commission.py`

**Backend — modified files:**
- `backend/src/booking/models.py` — four new nullable columns on `Booking`
- `backend/src/admin/service.py:188-238` — `confirm_payment` calls `snapshot_commission` before commit
- `backend/src/booking/service.py:246-284` — `list_provider_bookings` adds `commission_amount` + `net_amount` to each row
- `backend/src/booking/schemas.py:99-119` — `ProviderBookingItem` gains the two fields
- `backend/src/main.py` — registers `finance_router`; calls new `_migrate_if_needed()` from lifespan
- `backend/requirements.txt` — add `pytest==8.3.4`

**Frontend — modified files (everything is in one file):**
- `frontend/index.html` — gear icon, `#screen-admin-settings`, settings CSS, commissions JS, modal markup, i18n table additions (~35 keys × 2 languages)

---

## Task 1: Test scaffolding (pytest + conftest)

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add pytest to requirements**

Append to `backend/requirements.txt`:
```
pytest==8.3.4
httpx==0.27.2
```

- [ ] **Step 2: Install + sanity check**

Run from `backend/`:
```
source venv/bin/activate && pip install pytest==8.3.4 httpx==0.27.2 && pytest --version
```
Expected: `pytest 8.3.4`

- [ ] **Step 3: Create empty test package marker**

Create `backend/tests/__init__.py` with no content (empty file).

- [ ] **Step 4: Create `backend/tests/conftest.py`**

```python
"""Shared pytest fixtures. Tests use an in-memory SQLite DB and create
all tables fresh per test session — never touches the dev Postgres."""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Register every model with Base so create_all() builds the full schema.
    from src.database import Base
    import src.auth.models  # noqa: F401
    import src.inventory.models  # noqa: F401
    import src.booking.models  # noqa: F401
    import src.finance.models  # noqa: F401
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db(engine):
    """Per-test session. Wraps in a SAVEPOINT-style rollback so tests
    are isolated even when they hit the same in-memory DB."""
    connection = engine.connect()
    trans = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def client(engine):
    """FastAPI test client. Overrides get_db to return a fresh session
    bound to the in-memory engine."""
    from src.database import get_db
    from src.main import app
    Session = sessionmaker(bind=engine)

    def _get_db_override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
    """Seed an admin user and return it."""
    from src.auth.models import User
    from src.auth.utils import hash_password
    user = User(
        email="admin-test@tazkirati.app",
        full_name="Admin Test",
        password_hash=hash_password("Test#2026"),
        role="admin",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def provider_user(db):
    from src.auth.models import User
    from src.auth.utils import hash_password
    user = User(
        email="provider-test@tazkirati.app",
        full_name="Provider Test",
        password_hash=hash_password("Test#2026"),
        role="provider",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_header(client, admin_user):
    """Login the admin and return an Authorization header."""
    r = client.post("/auth/login", json={
        "email": admin_user.email,
        "password": "Test#2026",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
```

- [ ] **Step 5: Run pytest to confirm scaffolding boots**

Run from `backend/`:
```
PYTHONPATH=. pytest tests/ -v
```
Expected: `0 passed` (no test files exist yet, but no collection errors).

- [ ] **Step 6: Commit**

```
git add backend/requirements.txt backend/tests/__init__.py backend/tests/conftest.py
git commit -m "test: pytest scaffolding (sqlite in-memory, shared fixtures)"
```

---

## Task 2: `CommissionRule` ORM model

**Files:**
- Modify: `backend/src/finance/models.py`
- Create: `backend/tests/finance/__init__.py`
- Create: `backend/tests/finance/test_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/finance/__init__.py` (empty).

Create `backend/tests/finance/test_model.py`:
```python
from src.finance.models import CommissionRule


def test_commission_rule_has_required_columns():
    cols = {c.name for c in CommissionRule.__table__.columns}
    assert cols == {
        "id", "scope", "provider_id", "route_id", "trip_id",
        "rate_kind", "rate_value", "created_at", "updated_at",
    }


def test_commission_rule_unique_constraint():
    """The (scope, provider_id, route_id, trip_id) tuple must be unique."""
    cons = [c for c in CommissionRule.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"]
    assert len(cons) == 1
    names = {c.name for c in cons[0].columns}
    assert names == {"scope", "provider_id", "route_id", "trip_id"}


def test_commission_rule_insert_roundtrip(db):
    rule = CommissionRule(
        scope="global", rate_kind="percentage", rate_value=10.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    assert rule.id is not None
    assert rule.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

```
PYTHONPATH=. pytest tests/finance/test_model.py -v
```
Expected: ImportError or AttributeError — `CommissionRule` does not exist.

- [ ] **Step 3: Implement the model**

Replace `backend/src/finance/models.py` content with:
```python
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, UniqueConstraint,
)
from ..database import Base


class CommissionRule(Base):
    __tablename__ = "commission_rules"
    __table_args__ = (
        UniqueConstraint(
            "scope", "provider_id", "route_id", "trip_id",
            name="uq_commission_rule_target",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String, nullable=False, index=True)  # global | provider | provider_route | trip
    provider_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True, index=True)
    rate_kind = Column(String, nullable=False)  # percentage | flat_per_seat
    rate_value = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_model.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/src/finance/models.py backend/tests/finance/__init__.py backend/tests/finance/test_model.py
git commit -m "feat(finance): CommissionRule model + uniqueness on (scope, provider_id, route_id, trip_id)"
```

---

## Task 3: Booking row additions + idempotent ALTER TABLE migration

**Files:**
- Modify: `backend/src/booking/models.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: Add the four nullable columns to `Booking`**

In `backend/src/booking/models.py`, after the `seat_ids` column (line 31), add:
```python
    # Commission snapshot — populated by finance.service.snapshot_commission
    # at confirmation time. NULL for unconfirmed bookings and for walk-in
    # bookings (which keep only commission_amount=0).
    commission_amount = Column(Float, nullable=True)
    commission_rate_kind = Column(String, nullable=True)   # percentage | flat_per_seat
    commission_rate_value = Column(Float, nullable=True)
    commission_rule_id = Column(Integer, ForeignKey("commission_rules.id"), nullable=True)
```

- [ ] **Step 2: Add idempotent migration helper to `main.py`**

In `backend/src/main.py`, after `Base.metadata.create_all(bind=engine)` (line 16), add:
```python

def _migrate_if_needed():
    """Idempotent column additions for existing deployments. Postgres has
    `IF NOT EXISTS` since 9.6 so this is safe to run on every boot. SQLite
    test environments use create_all() which already covers the columns,
    so we skip the ALTER on SQLite."""
    from sqlalchemy import text
    if engine.dialect.name != "postgresql":
        return
    alters = [
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS commission_amount FLOAT",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS commission_rate_kind VARCHAR",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS commission_rate_value FLOAT",
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS commission_rule_id INTEGER REFERENCES commission_rules(id)",
    ]
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))
    print("[MIGRATE] commission columns ensured on bookings")
```

Then call it from the lifespan (around line 80, before `_bootstrap_if_empty()`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    _migrate_if_needed()
    _bootstrap_if_empty()
```

- [ ] **Step 3: Sanity test — booking model accepts the new columns**

Append to `backend/tests/finance/test_model.py`:
```python
def test_booking_has_commission_columns():
    from src.booking.models import Booking
    cols = {c.name for c in Booking.__table__.columns}
    assert "commission_amount" in cols
    assert "commission_rate_kind" in cols
    assert "commission_rate_value" in cols
    assert "commission_rule_id" in cols
```

Run:
```
PYTHONPATH=. pytest tests/finance/test_model.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```
git add backend/src/booking/models.py backend/src/main.py backend/tests/finance/test_model.py
git commit -m "feat(booking): four commission snapshot columns + idempotent ALTER TABLE migration"
```

---

## Task 4: `resolve_rule` — precedence resolver

**Files:**
- Modify: `backend/src/finance/service.py`
- Create: `backend/tests/finance/test_resolve_rule.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/finance/test_resolve_rule.py`:
```python
import pytest
from src.finance.models import CommissionRule
from src.finance.service import resolve_rule
from src.inventory.models import Trip, Route, Bus


@pytest.fixture
def trip(db, provider_user):
    route = Route(origin="Khartoum", destination="Port Sudan", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B1", seat_layout_config={"rows": 10, "config": "2x2"}, total_seats=45)
    db.add_all([route, bus])
    db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=__import__("datetime").datetime(2030, 1, 1, 12, 0),
        price=1000.0,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _mk(scope, **kw):
    return CommissionRule(scope=scope, rate_kind="percentage", rate_value=kw.pop("v", 5.0), **kw)


def test_no_rules_returns_none(db, trip):
    assert resolve_rule(db, trip) is None


def test_global_only(db, trip):
    db.add(_mk("global", v=10.0))
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "global" and r.rate_value == 10.0


def test_provider_beats_global(db, trip):
    db.add_all([_mk("global", v=10.0),
                _mk("provider", provider_id=trip.provider_id, v=8.0)])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "provider" and r.rate_value == 8.0


def test_provider_route_beats_provider(db, trip):
    db.add_all([
        _mk("global", v=10.0),
        _mk("provider", provider_id=trip.provider_id, v=8.0),
        _mk("provider_route", provider_id=trip.provider_id, route_id=trip.route_id, v=6.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "provider_route" and r.rate_value == 6.0


def test_trip_beats_everything(db, trip):
    db.add_all([
        _mk("global", v=10.0),
        _mk("provider", provider_id=trip.provider_id, v=8.0),
        _mk("provider_route", provider_id=trip.provider_id, route_id=trip.route_id, v=6.0),
        _mk("trip", provider_id=trip.provider_id, trip_id=trip.id, v=4.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "trip" and r.rate_value == 4.0


def test_other_provider_rules_ignored(db, trip):
    """A rule for a DIFFERENT provider's setup must not win."""
    db.add_all([
        _mk("provider", provider_id=trip.provider_id + 999, v=8.0),
        _mk("global", v=10.0),
    ])
    db.commit()
    r = resolve_rule(db, trip)
    assert r.scope == "global" and r.rate_value == 10.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/finance/test_resolve_rule.py -v
```
Expected: ImportError — `resolve_rule` does not exist.

- [ ] **Step 3: Implement the resolver**

Create or append to `backend/src/finance/service.py`:
```python
"""Commission rules — resolution + snapshot.

Spec: docs/superpowers/specs/2026-06-21-commissions-design.md
"""
from sqlalchemy.orm import Session

from .models import CommissionRule


def resolve_rule(db: Session, trip) -> CommissionRule | None:
    """Return the most specific rule that applies to this trip.

    Precedence (most specific first):
        trip > provider_route > provider > global

    Returns None if no rule at any tier (commission is then 0)."""
    # Tier 1 — explicit trip override
    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "trip",
                    CommissionRule.trip_id == trip.id)
            .first())
    if r:
        return r

    # Tier 2 — (provider + route) override
    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "provider_route",
                    CommissionRule.provider_id == trip.provider_id,
                    CommissionRule.route_id == trip.route_id)
            .first())
    if r:
        return r

    # Tier 3 — per-provider override
    r = (db.query(CommissionRule)
            .filter(CommissionRule.scope == "provider",
                    CommissionRule.provider_id == trip.provider_id)
            .first())
    if r:
        return r

    # Tier 4 — global default
    return (db.query(CommissionRule)
              .filter(CommissionRule.scope == "global")
              .first())
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_resolve_rule.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add backend/src/finance/service.py backend/tests/finance/test_resolve_rule.py
git commit -m "feat(finance): resolve_rule precedence (trip > provider_route > provider > global)"
```

---

## Task 5: `snapshot_commission` with walk-in short-circuit

**Files:**
- Modify: `backend/src/finance/service.py`
- Create: `backend/tests/finance/test_snapshot.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/finance/test_snapshot.py`:
```python
import pytest
from src.booking.models import Booking
from src.finance.models import CommissionRule
from src.finance.service import snapshot_commission
from src.inventory.models import Trip, Route, Bus


@pytest.fixture
def trip(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=__import__("datetime").datetime(2030, 1, 1),
        price=1000.0,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def _booking(trip, *, channel="consumer", total=2000.0, seats=2):
    return Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=total, channel=channel, payment_status="unpaid",
        seat_ids=list(range(1, seats + 1)),
    )


def test_no_rule_sets_zero(db, trip):
    b = _booking(trip)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rule_id is None


def test_percentage_rule(db, trip):
    rule = CommissionRule(scope="global", rate_kind="percentage", rate_value=8.0)
    db.add(rule); db.commit(); db.refresh(rule)
    b = _booking(trip, total=2000.0)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 160.0  # 8% of 2000
    assert b.commission_rate_kind == "percentage"
    assert b.commission_rate_value == 8.0
    assert b.commission_rule_id == rule.id


def test_flat_per_seat_rule(db, trip):
    rule = CommissionRule(scope="global", rate_kind="flat_per_seat", rate_value=150.0)
    db.add(rule); db.commit(); db.refresh(rule)
    b = _booking(trip, total=2000.0, seats=2)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 300.0  # 150 * 2 seats
    assert b.commission_rate_kind == "flat_per_seat"
    assert b.commission_rate_value == 150.0


def test_walkin_always_zero_even_with_rule(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = _booking(trip, channel="walkin", total=2000.0)
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rate_value is None
    assert b.commission_rule_id is None


def test_percentage_rounds_to_two_decimals(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=7.5))
    db.commit()
    b = _booking(trip, total=333.33)  # 7.5% = 24.99975 → 25.00
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 25.0


def test_empty_seat_ids_flat_yields_zero(db, trip):
    db.add(CommissionRule(scope="global", rate_kind="flat_per_seat", rate_value=150.0))
    db.commit()
    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=0.0, channel="consumer", payment_status="unpaid",
        seat_ids=[],
    )
    snapshot_commission(db, b, trip)
    assert b.commission_amount == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/finance/test_snapshot.py -v
```
Expected: ImportError — `snapshot_commission` does not exist.

- [ ] **Step 3: Implement `snapshot_commission`**

Append to `backend/src/finance/service.py`:
```python
def snapshot_commission(db: Session, booking, trip) -> None:
    """Set commission_* columns on the booking. Called once, at the
    moment a booking transitions to `confirmed`. Immutable thereafter.

    Walk-in bookings short-circuit to 0 regardless of any matching rule:
    the provider sold at their own counter, the platform took no cut.
    """
    if booking.channel == "walkin":
        booking.commission_amount = 0.0
        return

    rule = resolve_rule(db, trip)
    if rule is None:
        booking.commission_amount = 0.0
        return

    if rule.rate_kind == "percentage":
        amount = round(booking.total_price * (rule.rate_value / 100.0), 2)
    else:  # flat_per_seat
        seat_count = len(booking.seat_ids or [])
        amount = round(rule.rate_value * seat_count, 2)

    booking.commission_amount = amount
    booking.commission_rate_kind = rule.rate_kind
    booking.commission_rate_value = rule.rate_value
    booking.commission_rule_id = rule.id
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_snapshot.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add backend/src/finance/service.py backend/tests/finance/test_snapshot.py
git commit -m "feat(finance): snapshot_commission + walk-in short-circuit"
```

---

## Task 6: Wire snapshot into `confirm_payment`

**Files:**
- Modify: `backend/src/admin/service.py`
- Create: `backend/tests/booking/__init__.py`
- Create: `backend/tests/booking/test_confirm_path_snapshots_commission.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/booking/__init__.py` (empty).

Create `backend/tests/booking/test_confirm_path_snapshots_commission.py`:
```python
import pytest
from src.admin.service import confirm_payment
from src.booking.models import Booking
from src.finance.models import CommissionRule
from src.inventory.models import Trip, Route, Bus, Seat


@pytest.fixture
def trip_with_seats(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=__import__("datetime").datetime(2030, 1, 1),
        price=1000.0,
    )
    db.add(t); db.flush()
    seats = [Seat(trip_id=t.id, seat_number=f"{i}A", status="locked") for i in range(1, 3)]
    db.add_all(seats); db.commit()
    return t, seats


def _committed_booking(db, trip, seats, *, channel="consumer", total=2000.0):
    b = Booking(
        customer_id=1, trip_id=trip.id, status="committed_pending",
        total_price=total, channel=channel, payment_status="unpaid",
        seat_ids=[s.id for s in seats],
    )
    db.add(b); db.commit(); db.refresh(b)
    return b


def test_consumer_confirm_snapshots_commission(db, trip_with_seats):
    trip, seats = trip_with_seats
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=8.0))
    db.commit()
    b = _committed_booking(db, trip, seats, total=2000.0)
    confirm_payment(db, booking_id=b.id)
    db.refresh(b)
    assert b.status == "confirmed"
    assert b.commission_amount == 160.0
    assert b.commission_rate_kind == "percentage"


def test_walkin_confirm_zero_commission_even_with_rule(db, trip_with_seats):
    trip, seats = trip_with_seats
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = _committed_booking(db, trip, seats, channel="walkin", total=2000.0)
    confirm_payment(db, booking_id=b.id, payment_method="cash")
    db.refresh(b)
    assert b.status == "confirmed"
    assert b.commission_amount == 0.0
    assert b.commission_rate_kind is None
    assert b.commission_rule_id is None


def test_confirm_without_rules_zero(db, trip_with_seats):
    trip, seats = trip_with_seats
    b = _committed_booking(db, trip, seats)
    confirm_payment(db, booking_id=b.id)
    db.refresh(b)
    assert b.commission_amount == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/booking/test_confirm_path_snapshots_commission.py -v
```
Expected: `commission_amount` is `None` instead of `0.0` — snapshot never called.

- [ ] **Step 3: Wire the snapshot into `confirm_payment`**

In `backend/src/admin/service.py`, in `confirm_payment` (line 188), immediately before `db.commit()` (line 236), add:
```python
    # Commission snapshot — immutable record of (rate_kind, rate_value, rule_id)
    # at the moment of confirmation. Walk-ins short-circuit to 0 inside.
    from ..inventory.models import Trip as _Trip
    from ..finance.service import snapshot_commission
    _trip = db.query(_Trip).filter(_Trip.id == booking.trip_id).first()
    if _trip:
        snapshot_commission(db, booking, _trip)
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/booking/test_confirm_path_snapshots_commission.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/src/admin/service.py backend/tests/booking/__init__.py backend/tests/booking/test_confirm_path_snapshots_commission.py
git commit -m "feat(finance): snapshot commission on every confirm_payment (consumer + walk-in)"
```

---

## Task 7: Pydantic schemas for finance endpoints

**Files:**
- Modify: `backend/src/finance/schemas.py`

- [ ] **Step 1: Write the schemas**

Replace `backend/src/finance/schemas.py` content with:
```python
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


RateKind = Literal["percentage", "flat_per_seat"]
Scope = Literal["global", "provider", "provider_route", "trip"]


class GlobalUpsertIn(BaseModel):
    rate_kind: RateKind
    rate_value: float

    def validate_value(self) -> None:
        """Called by the router after parsing. Raises HTTPException(400)
        if the (rate_kind, rate_value) combination is invalid."""
        from fastapi import HTTPException
        if self.rate_kind == "percentage" and not (0 < self.rate_value <= 100):
            raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
        if self.rate_kind == "flat_per_seat" and self.rate_value <= 0:
            raise HTTPException(400, "Flat rate must be > 0")


class OverrideCreateIn(BaseModel):
    scope: Literal["provider", "provider_route", "trip"]
    provider_id: int
    route_id: Optional[int] = None
    trip_id: Optional[int] = None
    rate_kind: RateKind
    rate_value: float

    def validate_shape(self) -> None:
        """Router calls this. Enforces field presence per scope."""
        from fastapi import HTTPException
        if self.scope == "provider_route" and self.route_id is None:
            raise HTTPException(400, "route_id required for provider_route scope")
        if self.scope == "trip" and self.trip_id is None:
            raise HTTPException(400, "trip_id required for trip scope")
        if self.scope == "provider" and (self.route_id or self.trip_id):
            raise HTTPException(400, "route_id/trip_id not allowed for provider scope")
        if self.rate_kind == "percentage" and not (0 < self.rate_value <= 100):
            raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
        if self.rate_kind == "flat_per_seat" and self.rate_value <= 0:
            raise HTTPException(400, "Flat rate must be > 0")


class OverrideUpdateIn(BaseModel):
    rate_kind: RateKind
    rate_value: float


class GlobalRuleOut(BaseModel):
    rate_kind: RateKind
    rate_value: float
    updated_at: datetime


class OverrideRuleOut(BaseModel):
    id: int
    scope: Scope
    provider_id: int
    provider_name: str
    route_id: Optional[int] = None
    route_label: Optional[str] = None
    trip_id: Optional[int] = None
    trip_label: Optional[str] = None
    rate_kind: RateKind
    rate_value: float
    updated_at: datetime


class CommissionsReadResponse(BaseModel):
    global_rule: Optional[GlobalRuleOut] = Field(default=None, alias="global")
    overrides: List[OverrideRuleOut]

    class Config:
        populate_by_name = True
```

- [ ] **Step 2: Sanity import check**

```
PYTHONPATH=. python -c "from src.finance.schemas import CommissionsReadResponse; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```
git add backend/src/finance/schemas.py
git commit -m "feat(finance): Pydantic schemas for commission endpoints"
```

---

## Task 8: Service helpers — `list_overrides`, `upsert_global`, override CRUD

**Files:**
- Modify: `backend/src/finance/service.py`
- Create: `backend/tests/finance/test_service_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/finance/test_service_helpers.py`:
```python
import pytest
from src.finance.models import CommissionRule
from src.finance import service as fin
from src.inventory.models import Trip, Route, Bus


@pytest.fixture
def trip(db, provider_user):
    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    t = Trip(
        provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
        departure_time=__import__("datetime").datetime(2030, 1, 1, 12, 0),
        price=1000.0,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def test_upsert_global_inserts_when_missing(db):
    rule = fin.upsert_global(db, rate_kind="percentage", rate_value=8.0)
    assert rule.id is not None
    assert rule.scope == "global"


def test_upsert_global_updates_singleton(db):
    fin.upsert_global(db, rate_kind="percentage", rate_value=8.0)
    rule = fin.upsert_global(db, rate_kind="flat_per_seat", rate_value=150.0)
    assert db.query(CommissionRule).filter_by(scope="global").count() == 1
    assert rule.rate_kind == "flat_per_seat"


def test_create_override_provider(db, provider_user):
    o = fin.create_override(db, scope="provider", provider_id=provider_user.id,
                            route_id=None, trip_id=None,
                            rate_kind="percentage", rate_value=8.0)
    assert o.id is not None
    assert o.scope == "provider"


def test_create_override_duplicate_raises_409(db, provider_user):
    fin.create_override(db, scope="provider", provider_id=provider_user.id,
                        route_id=None, trip_id=None,
                        rate_kind="percentage", rate_value=8.0)
    with pytest.raises(Exception) as exc:
        fin.create_override(db, scope="provider", provider_id=provider_user.id,
                            route_id=None, trip_id=None,
                            rate_kind="percentage", rate_value=10.0)
    # FastAPI HTTPException doesn't expose status_code via .args reliably across versions;
    # the router validates and translates. Service raises HTTPException(409).
    from fastapi import HTTPException
    assert isinstance(exc.value, HTTPException) and exc.value.status_code == 409


def test_create_override_trip_must_belong_to_provider(db, provider_user, trip):
    from fastapi import HTTPException
    other_provider_id = provider_user.id + 999
    with pytest.raises(HTTPException) as exc:
        fin.create_override(db, scope="trip", provider_id=other_provider_id,
                            route_id=None, trip_id=trip.id,
                            rate_kind="percentage", rate_value=5.0)
    assert exc.value.status_code == 400


def test_list_overrides_decorates(db, provider_user, trip):
    fin.create_override(db, scope="provider", provider_id=provider_user.id,
                        route_id=None, trip_id=None,
                        rate_kind="percentage", rate_value=8.0)
    fin.create_override(db, scope="trip", provider_id=provider_user.id,
                        route_id=None, trip_id=trip.id,
                        rate_kind="percentage", rate_value=4.0)
    rows = fin.list_overrides(db)
    # Sorted by specificity descending: trip first, then provider.
    assert rows[0]["scope"] == "trip"
    assert rows[0]["trip_label"].startswith(f"Trip #{trip.id}")
    assert rows[0]["provider_name"] == provider_user.full_name
    assert rows[1]["scope"] == "provider"


def test_update_override(db, provider_user):
    o = fin.create_override(db, scope="provider", provider_id=provider_user.id,
                            route_id=None, trip_id=None,
                            rate_kind="percentage", rate_value=8.0)
    updated = fin.update_override(db, override_id=o.id,
                                  rate_kind="flat_per_seat", rate_value=200.0)
    assert updated.rate_kind == "flat_per_seat" and updated.rate_value == 200.0


def test_delete_override(db, provider_user):
    o = fin.create_override(db, scope="provider", provider_id=provider_user.id,
                            route_id=None, trip_id=None,
                            rate_kind="percentage", rate_value=8.0)
    fin.delete_override(db, override_id=o.id)
    assert db.query(CommissionRule).filter_by(id=o.id).count() == 0


def test_delete_override_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        fin.delete_override(db, override_id=9999)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/finance/test_service_helpers.py -v
```
Expected: ImportError — helpers don't exist.

- [ ] **Step 3: Implement the service helpers**

Append to `backend/src/finance/service.py`:
```python
# ---------------------------------------------------------------------------
# Admin-facing helpers (called from finance/router.py)
# ---------------------------------------------------------------------------

def get_global(db: Session):
    return (db.query(CommissionRule)
              .filter(CommissionRule.scope == "global")
              .first())


def upsert_global(db: Session, *, rate_kind: str, rate_value: float):
    rule = get_global(db)
    if rule is None:
        rule = CommissionRule(
            scope="global", rate_kind=rate_kind, rate_value=rate_value,
        )
        db.add(rule)
    else:
        rule.rate_kind = rate_kind
        rule.rate_value = rate_value
    db.commit()
    db.refresh(rule)
    return rule


def create_override(
    db: Session, *, scope: str, provider_id: int,
    route_id: int | None, trip_id: int | None,
    rate_kind: str, rate_value: float,
):
    from fastapi import HTTPException

    # Trip-scope rules must belong to the named provider.
    if scope == "trip":
        from ..inventory.models import Trip as _Trip
        trip = db.query(_Trip).filter(_Trip.id == trip_id).first()
        if not trip:
            raise HTTPException(404, f"Trip {trip_id} not found")
        if trip.provider_id != provider_id:
            raise HTTPException(
                400,
                "Trip does not belong to the named provider — pick the trip's actual operator.",
            )

    # Uniqueness — return 409 to invite an edit instead.
    existing = (db.query(CommissionRule)
                  .filter(CommissionRule.scope == scope,
                          CommissionRule.provider_id == provider_id,
                          CommissionRule.route_id == route_id,
                          CommissionRule.trip_id == trip_id)
                  .first())
    if existing:
        raise HTTPException(409, "Override already exists for this target — edit it instead.")

    rule = CommissionRule(
        scope=scope, provider_id=provider_id,
        route_id=route_id, trip_id=trip_id,
        rate_kind=rate_kind, rate_value=rate_value,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_override(db: Session, *, override_id: int, rate_kind: str, rate_value: float):
    from fastapi import HTTPException
    rule = (db.query(CommissionRule)
              .filter(CommissionRule.id == override_id,
                      CommissionRule.scope != "global")
              .first())
    if not rule:
        raise HTTPException(404, "Override not found")
    rule.rate_kind = rate_kind
    rule.rate_value = rate_value
    db.commit()
    db.refresh(rule)
    return rule


def delete_override(db: Session, *, override_id: int) -> None:
    from fastapi import HTTPException
    rule = (db.query(CommissionRule)
              .filter(CommissionRule.id == override_id,
                      CommissionRule.scope != "global")
              .first())
    if not rule:
        raise HTTPException(404, "Override not found")
    db.delete(rule)
    db.commit()


def _decorate_override(db: Session, rule: CommissionRule) -> dict:
    """Hydrate the human-readable labels the frontend renders."""
    from ..auth.models import User
    from ..inventory.models import Trip as _Trip, Route as _Route

    provider = db.query(User).filter(User.id == rule.provider_id).first()
    out = {
        "id": rule.id,
        "scope": rule.scope,
        "provider_id": rule.provider_id,
        "provider_name": provider.full_name if provider else "—",
        "route_id": rule.route_id,
        "route_label": None,
        "trip_id": rule.trip_id,
        "trip_label": None,
        "rate_kind": rule.rate_kind,
        "rate_value": rule.rate_value,
        "updated_at": rule.updated_at,
    }
    if rule.route_id:
        route = db.query(_Route).filter(_Route.id == rule.route_id).first()
        if route:
            out["route_label"] = f"{route.origin} → {route.destination}"
    if rule.trip_id:
        trip = db.query(_Trip).filter(_Trip.id == rule.trip_id).first()
        if trip:
            out["trip_label"] = (
                f"Trip #{trip.id} · {trip.departure_time.strftime('%Y-%m-%d %H:%M')}"
            )
    return out


_SCOPE_ORDER = {"trip": 0, "provider_route": 1, "provider": 2}


def list_overrides(db: Session) -> list[dict]:
    """All non-global rules, sorted by specificity descending."""
    rules = (db.query(CommissionRule)
               .filter(CommissionRule.scope != "global")
               .all())
    decorated = [_decorate_override(db, r) for r in rules]
    decorated.sort(key=lambda r: (_SCOPE_ORDER.get(r["scope"], 9), r["updated_at"]),
                   reverse=False)
    # We want trip first (order 0), then provider_route (1), then provider (2).
    return decorated
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_service_helpers.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```
git add backend/src/finance/service.py backend/tests/finance/test_service_helpers.py
git commit -m "feat(finance): admin CRUD helpers + override decoration"
```

---

## Task 9: Finance router + register in main.py

**Files:**
- Modify: `backend/src/finance/router.py`
- Modify: `backend/src/main.py`
- Create: `backend/tests/finance/test_admin_commissions_api.py`

- [ ] **Step 1: Write the failing endpoint tests**

Create `backend/tests/finance/test_admin_commissions_api.py`:
```python
def test_get_commissions_empty(client, auth_header):
    r = client.get("/admin/commissions", headers=auth_header)
    assert r.status_code == 200
    assert r.json() == {"global": None, "overrides": []}


def test_put_global_inserts_then_updates(client, auth_header):
    r = client.put("/admin/commissions/global",
                   json={"rate_kind": "percentage", "rate_value": 8.0},
                   headers=auth_header)
    assert r.status_code == 200
    r2 = client.put("/admin/commissions/global",
                    json={"rate_kind": "flat_per_seat", "rate_value": 150.0},
                    headers=auth_header)
    assert r2.status_code == 200
    r3 = client.get("/admin/commissions", headers=auth_header)
    assert r3.json()["global"]["rate_kind"] == "flat_per_seat"


def test_put_global_validates_range(client, auth_header):
    r = client.put("/admin/commissions/global",
                   json={"rate_kind": "percentage", "rate_value": 150.0},
                   headers=auth_header)
    assert r.status_code == 400


def test_create_override_provider(client, auth_header, db, provider_user):
    r = client.post("/admin/commissions/overrides", headers=auth_header, json={
        "scope": "provider", "provider_id": provider_user.id,
        "rate_kind": "percentage", "rate_value": 8.0,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider_name"] == provider_user.full_name


def test_create_override_duplicate_returns_409(client, auth_header, provider_user):
    payload = {"scope": "provider", "provider_id": provider_user.id,
               "rate_kind": "percentage", "rate_value": 8.0}
    client.post("/admin/commissions/overrides", headers=auth_header, json=payload)
    r = client.post("/admin/commissions/overrides", headers=auth_header, json=payload)
    assert r.status_code == 409


def test_patch_override(client, auth_header, provider_user):
    r = client.post("/admin/commissions/overrides", headers=auth_header, json={
        "scope": "provider", "provider_id": provider_user.id,
        "rate_kind": "percentage", "rate_value": 8.0,
    })
    rid = r.json()["id"]
    r2 = client.patch(f"/admin/commissions/overrides/{rid}", headers=auth_header,
                      json={"rate_kind": "percentage", "rate_value": 12.0})
    assert r2.status_code == 200
    assert r2.json()["rate_value"] == 12.0


def test_delete_override(client, auth_header, provider_user):
    r = client.post("/admin/commissions/overrides", headers=auth_header, json={
        "scope": "provider", "provider_id": provider_user.id,
        "rate_kind": "percentage", "rate_value": 8.0,
    })
    rid = r.json()["id"]
    r2 = client.delete(f"/admin/commissions/overrides/{rid}", headers=auth_header)
    assert r2.status_code == 204


def test_non_admin_gets_403(client, db):
    # Login as customer
    from src.auth.models import User
    from src.auth.utils import hash_password
    u = User(email="cust@x.com", full_name="C", password_hash=hash_password("Test#2026"),
            role="customer", status="active", email_verified=True)
    db.add(u); db.commit()
    r = client.post("/auth/login", json={"email": "cust@x.com", "password": "Test#2026"})
    token = r.json()["token"]
    r2 = client.get("/admin/commissions", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/finance/test_admin_commissions_api.py -v
```
Expected: 404 on every route — finance router not registered.

- [ ] **Step 3: Implement the router**

Replace `backend/src/finance/router.py` content with:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import require_admin
from ..database import get_db
from . import schemas, service

router = APIRouter(
    prefix="/admin/commissions",
    tags=["Admin · Commissions"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=schemas.CommissionsReadResponse)
def get_commissions(db: Session = Depends(get_db)):
    g = service.get_global(db)
    return {
        "global": (
            {
                "rate_kind": g.rate_kind,
                "rate_value": g.rate_value,
                "updated_at": g.updated_at,
            }
            if g else None
        ),
        "overrides": service.list_overrides(db),
    }


@router.put("/global", response_model=schemas.GlobalRuleOut)
def put_global(payload: schemas.GlobalUpsertIn, db: Session = Depends(get_db)):
    payload.validate_value()
    rule = service.upsert_global(
        db, rate_kind=payload.rate_kind, rate_value=payload.rate_value,
    )
    return {
        "rate_kind": rule.rate_kind,
        "rate_value": rule.rate_value,
        "updated_at": rule.updated_at,
    }


@router.post("/overrides", response_model=schemas.OverrideRuleOut, status_code=201)
def create_override(payload: schemas.OverrideCreateIn, db: Session = Depends(get_db)):
    payload.validate_shape()
    rule = service.create_override(
        db,
        scope=payload.scope,
        provider_id=payload.provider_id,
        route_id=payload.route_id,
        trip_id=payload.trip_id,
        rate_kind=payload.rate_kind,
        rate_value=payload.rate_value,
    )
    return service._decorate_override(db, rule)


@router.patch("/overrides/{override_id}", response_model=schemas.OverrideRuleOut)
def patch_override(
    override_id: int,
    payload: schemas.OverrideUpdateIn,
    db: Session = Depends(get_db),
):
    if payload.rate_kind == "percentage" and not (0 < payload.rate_value <= 100):
        from fastapi import HTTPException
        raise HTTPException(400, "Percentage rate must be > 0 and ≤ 100")
    if payload.rate_kind == "flat_per_seat" and payload.rate_value <= 0:
        from fastapi import HTTPException
        raise HTTPException(400, "Flat rate must be > 0")
    rule = service.update_override(
        db,
        override_id=override_id,
        rate_kind=payload.rate_kind,
        rate_value=payload.rate_value,
    )
    return service._decorate_override(db, rule)


@router.delete("/overrides/{override_id}", status_code=204)
def remove_override(override_id: int, db: Session = Depends(get_db)):
    service.delete_override(db, override_id=override_id)
    return None
```

- [ ] **Step 4: Register the router in main.py**

In `backend/src/main.py`, after `from .admin.router import router as admin_router` (line 13), add:
```python
from .finance.router import router as finance_router
```
After `app.include_router(admin_router)` (line 108), add:
```python
app.include_router(finance_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_admin_commissions_api.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Commit**

```
git add backend/src/finance/router.py backend/src/main.py backend/tests/finance/test_admin_commissions_api.py
git commit -m "feat(finance): admin commission endpoints (read, global upsert, override CRUD)"
```

---

## Task 10: Provider booking visibility — `commission_amount` + `net_amount`

**Files:**
- Modify: `backend/src/booking/schemas.py`
- Modify: `backend/src/booking/service.py`
- Create: `backend/tests/finance/test_provider_booking_visibility.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/finance/test_provider_booking_visibility.py`:
```python
def test_provider_bookings_expose_commission_and_net(client, db, provider_user):
    """A confirmed consumer booking with a 10% commission exposes
    commission_amount=200 and net_amount=1800 on a 2000-SDG booking."""
    from src.inventory.models import Trip, Route, Bus, Seat
    from src.booking.models import Booking
    from src.finance.models import CommissionRule
    from src.admin.service import confirm_payment

    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    trip = Trip(provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
                departure_time=__import__("datetime").datetime(2030, 1, 1),
                price=1000.0)
    db.add(trip); db.flush()
    seats = [Seat(trip_id=trip.id, seat_number=f"{i}A", status="locked") for i in range(1, 3)]
    db.add_all(seats); db.commit()
    db.add(CommissionRule(scope="global", rate_kind="percentage", rate_value=10.0))
    db.commit()
    b = Booking(customer_id=1, trip_id=trip.id, status="committed_pending",
                total_price=2000.0, channel="consumer", payment_status="unpaid",
                seat_ids=[s.id for s in seats])
    db.add(b); db.commit(); db.refresh(b)
    confirm_payment(db, booking_id=b.id)

    # Now log in as provider and hit the listing
    r = client.post("/auth/login",
                    json={"email": provider_user.email, "password": "Test#2026"})
    token = r.json()["token"]
    r2 = client.get("/bookings/provider/mine",
                    headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["commission_amount"] == 200.0
    assert rows[0]["net_amount"] == 1800.0


def test_unconfirmed_booking_has_null_commission(client, db, provider_user):
    from src.inventory.models import Trip, Route, Bus, Seat
    from src.booking.models import Booking

    route = Route(origin="K", destination="P", duration="10h")
    bus = Bus(provider_id=provider_user.id, name="B", seat_layout_config={}, total_seats=45)
    db.add_all([route, bus]); db.flush()
    trip = Trip(provider_id=provider_user.id, bus_id=bus.id, route_id=route.id,
                departure_time=__import__("datetime").datetime(2030, 1, 1),
                price=1000.0)
    db.add(trip); db.flush()
    b = Booking(customer_id=1, trip_id=trip.id, status="pending",
                total_price=2000.0, channel="consumer", payment_status="unpaid",
                seat_ids=[])
    db.add(b); db.commit()

    r = client.post("/auth/login",
                    json={"email": provider_user.email, "password": "Test#2026"})
    token = r.json()["token"]
    r2 = client.get("/bookings/provider/mine",
                    headers={"Authorization": f"Bearer {token}"})
    rows = r2.json()
    assert rows[0]["commission_amount"] is None
    assert rows[0]["net_amount"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=. pytest tests/finance/test_provider_booking_visibility.py -v
```
Expected: KeyError or pydantic ValidationError — schema lacks fields.

- [ ] **Step 3: Extend the schema**

In `backend/src/booking/schemas.py`, in the `ProviderBookingItem` class (line 99), add two fields:
```python
    commission_amount: float | None = None
    net_amount: float | None = None
```

- [ ] **Step 4: Populate fields in the service**

In `backend/src/booking/service.py`, in `list_provider_bookings` (line 246), inside the `for b in rows` loop where the dict is built (line 267-283), add two keys:
```python
            "commission_amount": b.commission_amount,
            "net_amount": (
                round(b.total_price - b.commission_amount, 2)
                if b.commission_amount is not None and b.total_price is not None
                else None
            ),
```

- [ ] **Step 5: Run tests to verify they pass**

```
PYTHONPATH=. pytest tests/finance/test_provider_booking_visibility.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Full backend suite check**

```
PYTHONPATH=. pytest tests/ -v
```
Expected: all tests pass (estimated ~30 tests across the suite).

- [ ] **Step 7: Commit**

```
git add backend/src/booking/schemas.py backend/src/booking/service.py backend/tests/finance/test_provider_booking_visibility.py
git commit -m "feat(booking): provider sees commission_amount + net_amount on confirmed rows"
```

---

## Task 11: i18n keys (EN + AR)

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Locate the i18n table**

Open `frontend/index.html`. Find the `const I18N = { en: { ... } }` block (around line 1765 for `en`, line 1936 for `ar`).

- [ ] **Step 2: Add EN keys**

Inside the `en:` object, add a new block (anywhere after the existing keys, before the closing `}`):
```javascript
    // Commission system (admin Settings hub + provider visibility)
    'settings.title': 'Settings',
    'settings.crumb': 'Settings',
    'settings.section.commissions': 'Commissions',
    'settings.section.account': 'Account',
    'settings.section.account.soon': 'Coming soon · password reset and more.',
    'nav.settings': 'Settings',
    'commission.global.title': 'Global commission',
    'commission.global.lead': 'Default rate applied when no override exists for the trip\'s provider or route.',
    'commission.global.empty': 'No global commission set — bookings carry zero commission until you set one.',
    'commission.kind.percentage': 'Percentage',
    'commission.kind.flat': 'Flat per seat',
    'commission.value.percent.suffix': '%',
    'commission.value.flat.suffix': 'SDG / seat',
    'commission.save': 'Save commission',
    'commission.saved': 'Commission saved.',
    'commission.overrides.title': 'Overrides',
    'commission.overrides.lead': 'Override the global rate for a specific provider, route, or trip.',
    'commission.overrides.empty': 'No overrides yet.',
    'commission.overrides.add': 'Add override',
    'commission.overrides.scope.provider': 'Provider',
    'commission.overrides.scope.provider_route': 'Provider + Route',
    'commission.overrides.scope.trip': 'Trip',
    'commission.overrides.edit': 'Edit',
    'commission.overrides.delete': 'Delete',
    'commission.overrides.confirm_delete': 'Delete this override?',
    'commission.modal.title.add': 'Add override',
    'commission.modal.title.edit': 'Edit override',
    'commission.modal.field.scope': 'Scope',
    'commission.modal.field.provider': 'Provider',
    'commission.modal.field.route': 'Route',
    'commission.modal.field.trip': 'Trip',
    'commission.modal.field.rate_kind': 'Rate type',
    'commission.modal.field.rate_value': 'Rate',
    'commission.modal.placeholder.select': 'Select…',
    'commission.modal.error.dup': 'Override already exists — edit it from the list.',
    'provider.commission.col': 'Commission',
    'provider.commission.net': 'Net to you',
    'provider.commission.walkin_note': 'walk-in',
    'provider.commission.footer.gross': 'Gross',
    'provider.commission.footer.commission': 'Commission',
    'provider.commission.footer.net': 'Net',
```

- [ ] **Step 3: Add AR keys (mirror the same keys)**

Inside the `ar:` object, add the matching block:
```javascript
    // العمولات + إعدادات المشرف
    'settings.title': 'الإعدادات',
    'settings.crumb': 'الإعدادات',
    'settings.section.commissions': 'العمولات',
    'settings.section.account': 'الحساب',
    'settings.section.account.soon': 'قريباً · إعادة تعيين كلمة المرور والمزيد.',
    'nav.settings': 'الإعدادات',
    'commission.global.title': 'العمولة العامة',
    'commission.global.lead': 'النسبة الافتراضية عند عدم وجود استثناء للمشغّل أو المسار.',
    'commission.global.empty': 'لم يتم تعيين عمولة عامة — الحجوزات بدون عمولة حتى تقوم بتعيين قيمة.',
    'commission.kind.percentage': 'نسبة مئوية',
    'commission.kind.flat': 'مبلغ ثابت لكل مقعد',
    'commission.value.percent.suffix': '٪',
    'commission.value.flat.suffix': 'جنيه / مقعد',
    'commission.save': 'حفظ العمولة',
    'commission.saved': 'تم حفظ العمولة.',
    'commission.overrides.title': 'استثناءات',
    'commission.overrides.lead': 'استثناء النسبة العامة لمشغّل أو مسار أو رحلة محددة.',
    'commission.overrides.empty': 'لا توجد استثناءات بعد.',
    'commission.overrides.add': 'إضافة استثناء',
    'commission.overrides.scope.provider': 'مشغّل',
    'commission.overrides.scope.provider_route': 'مشغّل + مسار',
    'commission.overrides.scope.trip': 'رحلة',
    'commission.overrides.edit': 'تعديل',
    'commission.overrides.delete': 'حذف',
    'commission.overrides.confirm_delete': 'حذف هذا الاستثناء؟',
    'commission.modal.title.add': 'إضافة استثناء',
    'commission.modal.title.edit': 'تعديل استثناء',
    'commission.modal.field.scope': 'النطاق',
    'commission.modal.field.provider': 'المشغّل',
    'commission.modal.field.route': 'المسار',
    'commission.modal.field.trip': 'الرحلة',
    'commission.modal.field.rate_kind': 'نوع النسبة',
    'commission.modal.field.rate_value': 'القيمة',
    'commission.modal.placeholder.select': 'اختر…',
    'commission.modal.error.dup': 'الاستثناء موجود بالفعل — قم بتعديله من القائمة.',
    'provider.commission.col': 'العمولة',
    'provider.commission.net': 'صافي لك',
    'provider.commission.walkin_note': 'حجز عند المنفذ',
    'provider.commission.footer.gross': 'إجمالي',
    'provider.commission.footer.commission': 'العمولة',
    'provider.commission.footer.net': 'الصافي',
```

- [ ] **Step 4: Smoke-load the page locally**

Run from repo root:
```
cd backend && PYTHONPATH=. uvicorn src.main:app --reload --port 8000
```
Open `http://localhost:8000/app/` in a browser. The page should load with no console errors. Toggle EN/AR — no `[i18n missing]` warnings yet (we haven't wired the keys to elements; that's the next task).

- [ ] **Step 5: Commit**

```
git add frontend/index.html
git commit -m "feat(i18n): commission system keys (EN + AR)"
```

---

## Task 12: Gear icon in topbar (admin-only)

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add the gear button to the topbar markup**

In `frontend/index.html`, find the topbar block (around line 1272):
```html
  <header class="topbar" id="topbar">
    <div class="brand" id="brand-home">Tazkirati. <small>تذكرتي</small></div>
    <nav class="topbar-nav" id="topbar-nav" hidden></nav>
    <div class="topbar-right">
      <span class="lang-toggle" id="lang-toggle">
```

Add the gear button **before** the `<span class="lang-toggle"...>`:
```html
      <button class="gear-btn" id="settings-btn" data-i18n-aria="settings.title" aria-label="Settings" hidden>⚙</button>
```

- [ ] **Step 2: Style the gear button**

In the CSS block, after the `.lang-toggle button` rules (around line 186), add:
```css
  .gear-btn {
    appearance: none; background: transparent; border: 1.5px solid currentColor;
    color: inherit; font-size: 18px; line-height: 1; cursor: pointer;
    padding: 7px 11px; font-family: inherit;
    transition: background 180ms, color 180ms;
  }
  .gear-btn:hover { background: currentColor; color: var(--paper); }
  .topbar.role-admin .gear-btn:hover { color: var(--admin); }
```

- [ ] **Step 3: Wire visibility in `paintChrome`**

Find `paintChrome` (around line 2337). After the `applyStatusBarStyle(auth?.user?.role);` line (around line 2382), add:
```javascript
  // Gear icon is admin-only for now. Future roles get nothing.
  const gear = $('#settings-btn');
  if (gear) gear.hidden = (auth?.user?.role !== 'admin');
```

- [ ] **Step 4: Wire click → goto admin-settings**

Find the section where global click handlers are registered (search for `signout-btn` event listener, around line 3570). Add nearby (before the `welcome-card` handler):
```javascript
$('#settings-btn')?.addEventListener('click', () => goto('admin-settings'));
```

- [ ] **Step 5: Smoke test**

Reload the page → log in as admin → gear icon visible in topbar. Log out → gear hidden. Log in as customer → gear hidden.

- [ ] **Step 6: Commit**

```
git add frontend/index.html
git commit -m "feat(ui): admin-only gear icon in topbar opens settings"
```

---

## Task 13: `#screen-admin-settings` scaffold + section CSS

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add the screen `<section>` markup**

Find the main canvas (around line 1293). After the existing `#screen-admin-home` `<section>` closes (find where it ends), add a new screen:
```html
    <!-- Admin Settings hub -->
    <section class="screen" id="screen-admin-settings">
      <div class="admin-stage">
        <h2 data-i18n="settings.title">Settings</h2>

        <section class="settings-section">
          <h3 data-i18n="settings.section.commissions">Commissions</h3>
          <div class="settings-body">
            <!-- Global commission card -->
            <div class="panel" id="commission-global-card">
              <h4 data-i18n="commission.global.title">Global commission</h4>
              <p class="lead" data-i18n="commission.global.lead">Default rate applied when no override exists.</p>
              <div id="commission-global-empty" class="empty-state" data-i18n="commission.global.empty">No global commission set yet.</div>
              <form id="commission-global-form" class="hidden">
                <div class="field-block">
                  <label data-i18n="commission.modal.field.rate_kind">Rate type</label>
                  <div class="role-pick" id="commission-global-kind">
                    <label class="active" data-kind="percentage">
                      <input type="radio" name="cg-kind" value="percentage" checked>
                      <span class="rp-title" data-i18n="commission.kind.percentage">Percentage</span>
                    </label>
                    <label data-kind="flat_per_seat">
                      <input type="radio" name="cg-kind" value="flat_per_seat">
                      <span class="rp-title" data-i18n="commission.kind.flat">Flat per seat</span>
                    </label>
                  </div>
                </div>
                <div class="field-block">
                  <label data-i18n="commission.modal.field.rate_value">Rate</label>
                  <input type="number" id="commission-global-value" min="0.01" step="0.01" />
                </div>
                <button class="cta admin" id="commission-global-save" data-i18n="commission.save">Save commission</button>
              </form>
            </div>

            <!-- Overrides -->
            <div class="panel" id="commission-overrides-card">
              <div class="panel-head">
                <h4 data-i18n="commission.overrides.title">Overrides</h4>
                <button class="btn-inline admin" id="commission-overrides-add" data-i18n="commission.overrides.add">Add override</button>
              </div>
              <p class="lead" data-i18n="commission.overrides.lead">Override the global rate for a specific provider, route, or trip.</p>
              <div id="commission-overrides-list"></div>
              <div id="commission-overrides-empty" class="empty-state" data-i18n="commission.overrides.empty">No overrides yet.</div>
            </div>
          </div>
        </section>

        <section class="settings-section disabled">
          <h3 data-i18n="settings.section.account">Account</h3>
          <div class="settings-body">
            <p class="lead" data-i18n="settings.section.account.soon">Coming soon.</p>
          </div>
        </section>
      </div>
    </section>
```

- [ ] **Step 2: Register the screen in the show/hide map**

Find the CSS map that controls which screen is visible (around line 582):
```css
  body[data-screen="welcome"]               #screen-welcome,
  ...
  body[data-screen="admin-home"]            #screen-admin-home { display: block; }
```

Add a line before `#screen-admin-home`:
```css
  body[data-screen="admin-settings"]        #screen-admin-settings,
```

- [ ] **Step 3: Add settings section CSS**

In the CSS block, after the `.admin-stage` rules (around line 928), add:
```css
  .settings-section { margin: 28px 0; }
  .settings-section h3 {
    font-family: 'Fraunces', serif; font-weight: 800; font-size: 22px;
    letter-spacing: -0.015em; margin: 0 0 12px;
    padding-bottom: 8px; border-bottom: 1.5px solid var(--rule);
  }
  .settings-section.disabled .settings-body { opacity: 0.5; pointer-events: none; }
  .settings-section .settings-body { display: flex; flex-direction: column; gap: 18px; }
  .settings-section .panel {
    background: var(--bone); border: 1.5px solid var(--rule);
    padding: 22px;
  }
  .settings-section .panel h4 {
    font-family: 'Fraunces', serif; font-weight: 800; font-size: 18px;
    letter-spacing: -0.005em; margin: 0 0 6px;
  }
  .settings-section .panel-head {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
  }

  /* Override list rows */
  .commission-override-row {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 0; border-bottom: 1px dashed var(--rule);
  }
  .commission-override-row:last-child { border-bottom: 0; }
  .commission-override-row .scope-badge {
    font-family: 'JetBrains Mono', monospace; font-size: 9px;
    letter-spacing: 0.18em; text-transform: uppercase;
    padding: 3px 8px; background: var(--admin); color: var(--bone);
  }
  .commission-override-row .label { flex: 1; font-weight: 600; }
  .commission-override-row .rate {
    font-family: 'JetBrains Mono', monospace; font-size: 13px;
  }
  .commission-override-row .actions { display: flex; gap: 6px; }
  .commission-override-row button {
    appearance: none; background: transparent; border: 1px solid var(--rule);
    padding: 5px 10px; font-size: 11px; cursor: pointer;
    font-family: inherit;
  }
  .commission-override-row button:hover { background: var(--ink); color: var(--bone); }
```

- [ ] **Step 4: Wire `goto('admin-settings')` to load data**

Find the `goto` and `s === 'admin-home'` block (around line 2150 / 2147). Add an `else if` branch for the new screen:
```javascript
  if (s === 'admin-home')          refreshAdminTab();
  else if (s === 'admin-settings') refreshAdminSettings();
```

Add the function (place it near `refreshAdminTab`, around line 3331):
```javascript
async function refreshAdminSettings() {
  // Loads global + overrides into the Settings → Commissions section.
  try {
    const data = await api('GET', '/admin/commissions');
    renderGlobalCommission(data.global);
    renderOverrideList(data.overrides || []);
  } catch (e) { toast(e.message, true); }
}

function renderGlobalCommission(g) {
  const empty = $('#commission-global-empty');
  const form  = $('#commission-global-form');
  if (!g) {
    empty.classList.remove('hidden');
    form.classList.add('hidden');
    return;
  }
  empty.classList.add('hidden');
  form.classList.remove('hidden');
  // Select the right radio
  $$('#commission-global-kind label').forEach(l => {
    l.classList.toggle('active', l.dataset.kind === g.rate_kind);
    const inp = l.querySelector('input');
    if (inp) inp.checked = (l.dataset.kind === g.rate_kind);
  });
  $('#commission-global-value').value = g.rate_value;
}

function renderOverrideList(rows) {
  const wrap = $('#commission-overrides-list');
  const empty = $('#commission-overrides-empty');
  wrap.innerHTML = '';
  if (rows.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');
  rows.forEach(r => {
    const label = (r.scope === 'trip')           ? r.trip_label
                : (r.scope === 'provider_route') ? `${r.provider_name} · ${r.route_label}`
                :                                  r.provider_name;
    const rateText = (r.rate_kind === 'percentage')
      ? `${r.rate_value}${t('commission.value.percent.suffix')}`
      : `${r.rate_value} ${t('commission.value.flat.suffix')}`;
    const row = document.createElement('div');
    row.className = 'commission-override-row';
    row.innerHTML = `
      <span class="scope-badge">${t('commission.overrides.scope.' + r.scope)}</span>
      <span class="label">${escapeHtml(label || '—')}</span>
      <span class="rate">${escapeHtml(rateText)}</span>
      <span class="actions">
        <button class="edit" data-id="${r.id}" data-i18n="commission.overrides.edit">Edit</button>
        <button class="del"  data-id="${r.id}" data-i18n="commission.overrides.delete">Delete</button>
      </span>
    `;
    wrap.appendChild(row);
  });
  applyLanguage();
}
```

- [ ] **Step 5: Smoke test**

Reload, log in as admin, click gear → Settings screen renders with empty state. No errors in console.

- [ ] **Step 6: Commit**

```
git add frontend/index.html
git commit -m "feat(ui): admin-settings screen scaffold with Commissions section"
```

---

## Task 14: Global commission form behavior

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Wire the radio toggle**

Near the bottom of the script, in the event-binding region (search for `$$('.role-pick label')` or `$('#sign-in-btn')`), add:
```javascript
// Global commission — radio toggle highlight
$$('#commission-global-kind label').forEach(l => {
  l.addEventListener('click', () => {
    $$('#commission-global-kind label').forEach(x => x.classList.remove('active'));
    l.classList.add('active');
    const inp = l.querySelector('input');
    if (inp) inp.checked = true;
  });
});
```

- [ ] **Step 2: Wire the empty-state "click to set" + Save button**

Add nearby:
```javascript
// First-time entry: clicking the empty-state reveals the form.
$('#commission-global-empty')?.addEventListener('click', () => {
  $('#commission-global-empty').classList.add('hidden');
  $('#commission-global-form').classList.remove('hidden');
});

// Save → PUT /admin/commissions/global
$('#commission-global-save')?.addEventListener('click', async (e) => {
  e.preventDefault();
  const active = $('#commission-global-kind label.active');
  const kind = active?.dataset.kind || 'percentage';
  const value = parseFloat($('#commission-global-value').value);
  if (!isFinite(value) || value <= 0) {
    return toast(t('commission.modal.field.rate_value') + ' ?', true);
  }
  try {
    await api('PUT', '/admin/commissions/global',
              { rate_kind: kind, rate_value: value });
    toast(t('commission.saved'));
    refreshAdminSettings();
  } catch (err) { toast(err.message, true); }
});
```

- [ ] **Step 3: Smoke test**

Reload as admin → Settings → click empty-state → set 8% → Save → toast "Commission saved" → page re-renders the form with the saved value. Refresh — value persists.

- [ ] **Step 4: Commit**

```
git add frontend/index.html
git commit -m "feat(ui): global commission form save/load"
```

---

## Task 15: Overrides — Add / Edit modal

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add the modal markup**

Near the existing modals (search for `id="ticket-modal"` or `id="add-trip-modal"`, around line 1646), add:
```html
<div id="commission-override-modal" class="modal-bg" role="dialog" aria-modal="true">
  <div class="modal-card">
    <h3 id="cov-title" data-i18n="commission.modal.title.add">Add override</h3>
    <div class="modal-sub" data-i18n="commission.overrides.lead">Override the global rate.</div>

    <div class="field-block">
      <label data-i18n="commission.modal.field.scope">Scope</label>
      <div class="role-pick" id="cov-scope">
        <label class="active" data-scope="provider">
          <input type="radio" name="cov-scope" value="provider" checked>
          <span class="rp-title" data-i18n="commission.overrides.scope.provider">Provider</span>
        </label>
        <label data-scope="provider_route">
          <input type="radio" name="cov-scope" value="provider_route">
          <span class="rp-title" data-i18n="commission.overrides.scope.provider_route">Provider + Route</span>
        </label>
        <label data-scope="trip">
          <input type="radio" name="cov-scope" value="trip">
          <span class="rp-title" data-i18n="commission.overrides.scope.trip">Trip</span>
        </label>
      </div>
    </div>

    <div class="field-block">
      <label data-i18n="commission.modal.field.provider">Provider</label>
      <select id="cov-provider"></select>
    </div>
    <div class="field-block hidden" id="cov-route-row">
      <label data-i18n="commission.modal.field.route">Route</label>
      <select id="cov-route"></select>
    </div>
    <div class="field-block hidden" id="cov-trip-row">
      <label data-i18n="commission.modal.field.trip">Trip</label>
      <select id="cov-trip"></select>
    </div>

    <div class="field-block">
      <label data-i18n="commission.modal.field.rate_kind">Rate type</label>
      <div class="role-pick" id="cov-kind">
        <label class="active" data-kind="percentage">
          <input type="radio" name="cov-kind" value="percentage" checked>
          <span class="rp-title" data-i18n="commission.kind.percentage">Percentage</span>
        </label>
        <label data-kind="flat_per_seat">
          <input type="radio" name="cov-kind" value="flat_per_seat">
          <span class="rp-title" data-i18n="commission.kind.flat">Flat per seat</span>
        </label>
      </div>
    </div>
    <div class="field-block">
      <label data-i18n="commission.modal.field.rate_value">Rate</label>
      <input type="number" id="cov-value" min="0.01" step="0.01" />
    </div>

    <div class="modal-actions">
      <button class="cta ghost" id="cov-cancel" data-i18n="ticket.close">Cancel</button>
      <button class="cta admin" id="cov-save" data-i18n="commission.save">Save</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Wire scope-pill + kind-pill toggles + open/close**

Append to the script (near the existing event bindings):
```javascript
// Commission override modal — open
$('#commission-overrides-add')?.addEventListener('click', () => openOverrideModal(null));

// Open helper: pass null to add, or a row dict to edit
let _covEditingId = null;
async function openOverrideModal(row) {
  _covEditingId = row?.id || null;
  $('#cov-title').textContent = t(row ? 'commission.modal.title.edit' : 'commission.modal.title.add');
  // Reset selections
  selectPillById('#cov-scope', row?.scope || 'provider');
  selectPillById('#cov-kind',  row?.rate_kind || 'percentage');
  $('#cov-value').value = row?.rate_value ?? '';
  // Load dropdown contents
  await populateProviderSelect(row?.provider_id);
  await populateRouteSelect(row?.provider_id, row?.route_id);
  await populateTripSelect(row?.provider_id, row?.trip_id);
  applyConditionalRows();
  $('#commission-override-modal').classList.add('show');
}

function selectPillById(rootSel, value) {
  $$(rootSel + ' label').forEach(l => {
    const key = l.dataset.scope || l.dataset.kind;
    l.classList.toggle('active', key === value);
    const inp = l.querySelector('input');
    if (inp) inp.checked = (key === value);
  });
}

function applyConditionalRows() {
  const scope = $('#cov-scope label.active')?.dataset.scope || 'provider';
  $('#cov-route-row').classList.toggle('hidden', scope !== 'provider_route');
  $('#cov-trip-row').classList.toggle('hidden',  scope !== 'trip');
}

$$('#cov-scope label').forEach(l => l.addEventListener('click', () => {
  selectPillById('#cov-scope', l.dataset.scope);
  applyConditionalRows();
}));
$$('#cov-kind label').forEach(l => l.addEventListener('click', () => {
  selectPillById('#cov-kind', l.dataset.kind);
}));

$('#cov-cancel')?.addEventListener('click', () => {
  $('#commission-override-modal').classList.remove('show');
});

async function populateProviderSelect(selectedId) {
  const sel = $('#cov-provider');
  const list = await api('GET', '/admin/providers?status=active');
  sel.innerHTML = `<option value="">${t('commission.modal.placeholder.select')}</option>` +
    list.map(p => `<option value="${p.id}" ${p.id === selectedId ? 'selected' : ''}>${escapeHtml(p.full_name)}</option>`).join('');
}

async function populateRouteSelect(_providerId, selectedId) {
  // Per spec §7.3: route picker shows all routes, not filtered to the
  // provider's trips, because backend allows pre-setting a rate.
  const sel = $('#cov-route');
  try {
    // No /routes endpoint exists; derive from /admin/trips
    const trips = await api('GET', '/admin/trips?time=all');
    const seen = new Map();
    trips.forEach(t => {
      if (t.route_id) seen.set(t.route_id, `${t.origin} → ${t.destination}`);
    });
    sel.innerHTML = `<option value="">${t('commission.modal.placeholder.select')}</option>` +
      [...seen.entries()].map(([id, label]) =>
        `<option value="${id}" ${id === selectedId ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
  } catch (e) { sel.innerHTML = ''; }
}

async function populateTripSelect(providerId, selectedId) {
  const sel = $('#cov-trip');
  if (!providerId) { sel.innerHTML = ''; return; }
  try {
    const trips = await api('GET', `/admin/trips?provider_id=${providerId}&time=upcoming`);
    sel.innerHTML = `<option value="">${t('commission.modal.placeholder.select')}</option>` +
      trips.map(tr => {
        const label = `Trip #${tr.trip_id} · ${tr.origin} → ${tr.destination} · ${fmtDate(tr.departure_time)}`;
        return `<option value="${tr.trip_id}" ${tr.trip_id === selectedId ? 'selected' : ''}>${escapeHtml(label)}</option>`;
      }).join('');
  } catch (e) { sel.innerHTML = ''; }
}

// When provider changes, refresh route + trip selects.
$('#cov-provider')?.addEventListener('change', async (e) => {
  await populateRouteSelect(parseInt(e.target.value) || null, null);
  await populateTripSelect(parseInt(e.target.value) || null, null);
});

// Save → POST or PATCH
$('#cov-save')?.addEventListener('click', async (e) => {
  e.preventDefault();
  const scope = $('#cov-scope label.active')?.dataset.scope || 'provider';
  const kind  = $('#cov-kind  label.active')?.dataset.kind  || 'percentage';
  const value = parseFloat($('#cov-value').value);
  if (!isFinite(value) || value <= 0) {
    return toast(t('commission.modal.field.rate_value') + ' ?', true);
  }
  try {
    if (_covEditingId) {
      await api('PATCH', `/admin/commissions/overrides/${_covEditingId}`,
                { rate_kind: kind, rate_value: value });
    } else {
      const body = {
        scope, rate_kind: kind, rate_value: value,
        provider_id: parseInt($('#cov-provider').value),
      };
      if (scope === 'provider_route') body.route_id = parseInt($('#cov-route').value);
      if (scope === 'trip')           body.trip_id  = parseInt($('#cov-trip').value);
      await api('POST', '/admin/commissions/overrides', body);
    }
    $('#commission-override-modal').classList.remove('show');
    refreshAdminSettings();
  } catch (err) {
    if (err.status === 409) toast(t('commission.modal.error.dup'), true);
    else toast(err.message, true);
  }
});

// Row edit + delete (delegated on the list)
$('#commission-overrides-list')?.addEventListener('click', async (e) => {
  const editBtn = e.target.closest('button.edit');
  const delBtn  = e.target.closest('button.del');
  if (editBtn) {
    const id = parseInt(editBtn.dataset.id);
    const data = await api('GET', '/admin/commissions');
    const row = (data.overrides || []).find(r => r.id === id);
    if (row) openOverrideModal(row);
  }
  if (delBtn) {
    if (!confirm(t('commission.overrides.confirm_delete'))) return;
    try {
      await api('DELETE', `/admin/commissions/overrides/${delBtn.dataset.id}`);
      refreshAdminSettings();
    } catch (err) { toast(err.message, true); }
  }
});
```

- [ ] **Step 2.5: Add a `fmtDate` helper if missing**

Search for `function fmtDate(`. If it doesn't exist, add nearby:
```javascript
function fmtDate(iso) {
  const d = parseUtc(iso);
  if (!d) return '—';
  return d.toLocaleString(LANG === 'ar' ? 'ar' : undefined,
    { dateStyle: 'short', timeStyle: 'short' });
}
```

- [ ] **Step 3: Smoke test**

Reload as admin → Settings → Add override → pick Provider, select a provider, set 8% → Save → row appears. Click Delete on the row → confirm → row disappears. Click Edit on a remaining row → modal pre-fills → change value → Save → row updates.

Test the duplicate 409: create the same provider override twice → second attempt shows "Override already exists" toast.

- [ ] **Step 4: Commit**

```
git add frontend/index.html
git commit -m "feat(ui): commission override add/edit/delete modal"
```

---

## Task 16: Provider Bookings — commission columns + footer totals

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Locate the provider booking row renderer**

Find where `/bookings/provider/mine` is rendered. Search for `provider-bookings-list` or `b.total_price` near a provider context. The function is roughly around `refreshProviderBookings()` (search for it).

- [ ] **Step 2: Add commission + net cells to each row**

In the row template (a string with `total_price` rendered), append two cells. The exact insertion depends on layout; the common pattern is:

```javascript
// Inside the row HTML template, after the existing total cell:
const commCell = (b.commission_amount == null)
  ? '—'
  : `SDG ${fmtMoney(b.commission_amount)}` +
    (b.channel === 'walkin'
      ? ` <small class="walkin-tag">(${t('provider.commission.walkin_note')})</small>`
      : '');
const netCell = (b.net_amount == null) ? '—' : `SDG ${fmtMoney(b.net_amount)}`;
// Then append into the row markup:
//   <div class="cell"><div class="k">${t('provider.commission.col')}</div><div class="v">${commCell}</div></div>
//   <div class="cell"><div class="k">${t('provider.commission.net')}</div><div class="v">${netCell}</div></div>
```

(If the row layout is table-style instead of cell-grid, append to the relevant container; copy the existing total-price cell's pattern verbatim and adjust.)

- [ ] **Step 3: Add a footer band with totals**

Below the bookings list container (search for the end of the provider bookings panel), add a footer summary:
```html
<div class="provider-bookings-footer" id="provider-bookings-footer" hidden>
  <span><b data-i18n="provider.commission.footer.gross">Gross</b>: SDG <span id="pbf-gross">0</span></span>
  <span><b data-i18n="provider.commission.footer.commission">Commission</b>: SDG <span id="pbf-commission">0</span></span>
  <span><b data-i18n="provider.commission.footer.net">Net</b>: SDG <span id="pbf-net">0</span></span>
</div>
```

Add CSS:
```css
.provider-bookings-footer {
  display: flex; flex-wrap: wrap; gap: 18px;
  padding: 12px 16px; margin-top: 12px;
  background: var(--bone); border: 1.5px solid var(--rule);
  font-family: 'JetBrains Mono', monospace; font-size: 12px;
  letter-spacing: 0.05em;
}
.provider-bookings-footer b {
  font-family: 'Fraunces', serif; font-weight: 700;
}
.walkin-tag {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace; font-size: 9px;
  color: var(--ink-soft); letter-spacing: 0.08em;
  margin-left: 4px;
}
```

- [ ] **Step 4: Compute totals after fetching**

In the function that fetches the provider bookings list (after `rows = await api(...)`):
```javascript
const confirmed = rows.filter(b => b.status === 'confirmed');
const gross  = confirmed.reduce((a, b) => a + (b.total_price || 0), 0);
const comm   = confirmed.reduce((a, b) => a + (b.commission_amount || 0), 0);
const net    = confirmed.reduce((a, b) => a + (b.net_amount || 0), 0);
$('#pbf-gross').textContent      = fmtMoney(Math.round(gross * 100) / 100);
$('#pbf-commission').textContent = fmtMoney(Math.round(comm  * 100) / 100);
$('#pbf-net').textContent        = fmtMoney(Math.round(net   * 100) / 100);
$('#provider-bookings-footer').hidden = (confirmed.length === 0);
```

- [ ] **Step 5: Mobile-collapse the commission column on narrow viewports**

In the `@media (max-width: 640px)` block (around line 216), add:
```css
.provider-bookings-list .cell.commission { display: none; }
.provider-bookings-list .booking-row.expanded .cell.commission { display: block; }
```

(Mark the commission cell with `class="cell commission"` in the row template so the rule targets it.)

- [ ] **Step 6: Smoke test (TDD via UI)**

Sequence: seed a global 10% rule → as customer, book + lock 2 seats on a Khartoum→Port Sudan trip @ 1000 SDG/seat → as admin, confirm payment → as provider on that trip, open My Bookings → row shows Commission SDG 200, Net SDG 1800 → footer shows Gross 2000, Commission 200, Net 1800.

Walk-in path: provider creates a walk-in → cash-confirms → row shows Commission SDG 0 with `(walk-in)` tag.

- [ ] **Step 7: Commit**

```
git add frontend/index.html
git commit -m "feat(ui): provider bookings show commission + net + totals footer"
```

---

## Task 17: Final smoke + suite + cleanup

- [ ] **Step 1: Full backend suite**

```
cd backend && PYTHONPATH=. pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 2: Manual EN/AR pass**

In the browser, open Settings as admin → flip to AR → every label translated, no `[i18n missing]` warnings. Override list rows in AR show RTL layout cleanly. Switch back to EN.

- [ ] **Step 3: Update CLAUDE.md**

Add a new "Recent fixes" entry at the top of the list:
```
- **Commission system landed (2026-06-21)**: three-tier rate hierarchy (trip > provider+route > provider > global) with immutable snapshot at confirmation. Walk-in bookings always 0%. Admin Settings hub reachable from the gear icon in the topbar; first section is Commissions (global form + overrides list + add/edit modal). Provider Bookings tab gains Commission + Net columns + a totals footer. New finance module: `backend/src/finance/{models,schemas,service,router}.py`. Four new nullable columns on `bookings` (`commission_amount`, `commission_rate_kind`, `commission_rate_value`, `commission_rule_id`) backfilled by an idempotent `ALTER TABLE IF NOT EXISTS` in `_migrate_if_needed()` at lifespan. ~35 i18n keys (EN + AR). Spec: `docs/superpowers/specs/2026-06-21-commissions-design.md`. Plan: `docs/superpowers/plans/2026-06-21-commissions.md`.
```

Also bump the "Deferred V2" section: remove "Commission rules + campaigns (Part 3.4–3.5)" or note that commission rules shipped while campaigns are still deferred.

- [ ] **Step 4: Commit + push**

```
git add claude.md
git commit -m "docs: commission system in claude.md"
git push
```

The push triggers Render redeploy. Lifespan runs `_migrate_if_needed()` on first boot → adds the four columns to the production `bookings` table.

---

## Self-review notes

- **Spec §1 (3-tier hierarchy)** — Task 4 implements resolver; tests cover every precedence case.
- **Spec §1 (channel rule, walk-ins = 0)** — Task 5 short-circuits; Task 6 integration test confirms walk-ins stay 0 even with a matching rule.
- **Spec §3.1 (commission_rules table)** — Task 2.
- **Spec §3.2 (booking columns)** — Task 3.
- **Spec §4 (resolver)** — Task 4.
- **Spec §5 (snapshot helper)** — Task 5.
- **Spec §6.1–6.3 (endpoints)** — Tasks 8 + 9.
- **Spec §6.4 (provider visibility)** — Task 10.
- **Spec §7.1–7.2 (gear + settings screen)** — Tasks 12 + 13.
- **Spec §7.3 (commissions section)** — Tasks 13–15.
- **Spec §7.4 (provider bookings UI)** — Task 16.
- **Spec §7.5 (i18n)** — Task 11.
- **Spec §8 (migration)** — Task 3.
- **Spec §9 (tests)** — Tasks 4, 5, 6, 8, 9, 10 each ship the test files §9 names.
- **Spec §11 (acceptance criteria)** — Task 17 manually verifies.

No placeholders. Types consistent between schema definitions and service/router usage (`rate_kind`, `rate_value`, `provider_id`, etc.).
