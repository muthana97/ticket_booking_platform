"""Shared pytest fixtures. Each test gets a fresh in-memory SQLite DB so
isolation is guaranteed without savepoint gymnastics. The client fixture
shares the same session as `db` so seed-then-request flows see the same data.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite needs an explicit pragma per connection to enforce FK constraints
    # (including ON DELETE SET NULL). Without it, tests pass that prod would fail.
    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # SQLAlchemy's documented pysqlite recipe: turn OFF pysqlite's own
        # transaction management (which relies on regex-matching statement
        # text and doesn't recognize SAVEPOINT/RELEASE SAVEPOINT), so
        # SQLAlchemy can drive BEGIN/SAVEPOINT/ROLLBACK correctly. Required
        # for db.begin_nested() to participate in outer-transaction rollback
        # (see backend/src/audit/service.py:record_event and spec §5.4).
        # Postgres/psycopg2 in prod doesn't need this — it's a pysqlite quirk.
        dbapi_connection.isolation_level = None

    @event.listens_for(eng, "begin")
    def _do_begin(conn):
        conn.exec_driver_sql("BEGIN")

    from src.database import Base
    import src.auth.models  # noqa: F401
    import src.inventory.models  # noqa: F401
    import src.booking.models  # noqa: F401
    import src.finance.models  # noqa: F401
    import src.notifications.models  # noqa: F401
    import src.promo.models  # noqa: F401
    import src.audit.models  # noqa: F401
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """FastAPI test client whose get_db dependency yields the SAME session
    as the `db` fixture, so seed-then-request flows see the same data."""
    from src.database import get_db
    from src.main import app

    def _get_db_override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
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
    r = client.post("/auth/login", json={
        "email": admin_user.email,
        "password": "Test#2026",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
