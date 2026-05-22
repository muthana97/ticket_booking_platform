from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import settings

# Render (and Heroku, ElephantSQL, etc.) hand out DATABASE_URL with the
# `postgres://` scheme, which SQLAlchemy 2.x no longer accepts. Normalize it.
_db_url = settings.DATABASE_URL
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

# Cloud-friendly engine config:
#   - pool_pre_ping: recover transparently from dropped connections (PaaS sleep)
#   - pool_size / max_overflow: tuned via env so the same code runs on
#     Render free tier (1 worker) and on a paid multi-worker plan.
engine = create_engine(
    _db_url,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
