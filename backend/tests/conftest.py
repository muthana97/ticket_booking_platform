"""Shared pytest fixtures. Tests use an in-memory SQLite DB and create
all tables fresh per test session — never touches the dev Postgres."""
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
    from src.database import Base
    import src.auth.models  # noqa: F401
    import src.inventory.models  # noqa: F401
    import src.booking.models  # noqa: F401
    import src.finance.models  # noqa: F401
    Base.metadata.create_all(bind=eng)
    return eng


@pytest.fixture
def db(engine):
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
    return {"Authorization": f"Bearer {r.json()['token']}"}
