import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from .config import settings
from .database import engine, Base
from .inventory.router import router as inventory_router
from .auth.router import router as auth_router
from .booking.router import router as booking_router
from .booking.tasks import cleanup_expired_bookings # <--- Import the task
from .admin.router import router as admin_router
from .finance.router import router as finance_router
from .notifications.router import router as notifications_router
# Import the model so Base.metadata.create_all() picks up the table.
from .notifications import models as _notifications_models  # noqa: F401

def _ensure_schema():
    """Create tables on the configured engine. Lifted out of module scope so
    importing `src.main` doesn't open a Postgres connection (matters for
    tests that swap the engine via dependency overrides)."""
    Base.metadata.create_all(bind=engine)


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
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP",
        "CREATE INDEX IF NOT EXISTS idx_bookings_confirmed_at ON bookings (confirmed_at)",
        # Phone is now optional on the passenger form (GEN-1). Existing rows
        # have values; DROP NOT NULL is a no-op for those.
        "ALTER TABLE passengers ALTER COLUMN phone_number DROP NOT NULL",
        # Per-provider capability toggles (ADMIN-2). Existing providers get
        # TRUE for all three so the migration is behavior-preserving.
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_add_trips BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_edit_trips BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS can_delete_trips BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS national_id VARCHAR",
    ]
    # The original FK above lacks ON DELETE SET NULL — drop + re-add so admins
    # can remove a rule even after it's been snapshotted onto a booking. The
    # historic rate_kind / rate_value / amount stay intact; only the pointer
    # is nulled.
    refk_fix = """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'bookings_commission_rule_id_fkey'
            ) THEN
                ALTER TABLE bookings DROP CONSTRAINT bookings_commission_rule_id_fkey;
            END IF;
            ALTER TABLE bookings
                ADD CONSTRAINT bookings_commission_rule_id_fkey
                FOREIGN KEY (commission_rule_id)
                REFERENCES commission_rules(id)
                ON DELETE SET NULL;
        END$$;
    """
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))
        conn.execute(text(refk_fix))
    print("[MIGRATE] commission columns ensured on bookings")

    backfill = (
        "UPDATE bookings "
        "SET confirmed_at = COALESCE(bill_generated_at, created_at) "
        "WHERE status = 'confirmed' AND confirmed_at IS NULL"
    )
    with engine.begin() as conn:
        conn.execute(text(backfill))
    print("[MIGRATE] confirmed_at column + backfill complete")


def _bootstrap_if_empty():
    """
    On every startup:
      1. If the DB has no admin → run seed_data() (free-tier has no shell to
         run `python seed.py` manually).
      2. If ADMIN_EMAIL and ADMIN_PASSWORD env vars are set, reconcile the
         existing admin row to match them — so changing the env vars in
         Render's UI actually takes effect on the next deploy without
         needing DB access.
    """
    import os
    try:
        from .auth.models import User
        from .auth.utils import hash_password
        from .database import SessionLocal

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.role == "admin").first()

            if admin is None:
                print("[BOOTSTRAP] empty DB — running seed_data()")
                db.close()
                from seed import seed_data
                seed_data()
                return

            # Reconcile admin to env vars if both are set.
            env_email = os.getenv("ADMIN_EMAIL")
            env_pw = os.getenv("ADMIN_PASSWORD")
            if env_email and env_pw:
                changed = False
                new_email = env_email.lower().strip()
                if admin.email != new_email:
                    admin.email = new_email
                    changed = True
                # Always re-hash from env on each boot — bcrypt salts differ
                # so we re-verify by trying to authenticate with the env pw.
                from .auth.utils import verify_password
                if not verify_password(env_pw, admin.password_hash):
                    admin.password_hash = hash_password(env_pw)
                    changed = True
                if changed:
                    db.commit()
                    print(f"[BOOTSTRAP] reconciled admin → {new_email}")
                else:
                    print(f"[BOOTSTRAP] admin already matches env ({new_email})")
            else:
                print("[BOOTSTRAP] admin present, env not set — leaving as-is")
        finally:
            try:
                db.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[BOOTSTRAP] failed: {e!r}")


# 1. Define the Lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    _ensure_schema()
    _migrate_if_needed()
    _bootstrap_if_empty()
    reaper_task = asyncio.create_task(cleanup_expired_bookings())

    yield  # The application serves requests here

    # SHUTDOWN
    reaper_task.cancel()

# 2. Initialize FastAPI with the lifespan
app = FastAPI(
    title="Ticket Booking Platform API",
    lifespan=lifespan
)

# 3. CORS — origin allowlist driven by settings.CORS_ALLOWED_ORIGINS env var.
#    Defaults to "*" for local dev; production must set explicit origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Include Routers
app.include_router(inventory_router)
app.include_router(auth_router)
app.include_router(booking_router)
app.include_router(admin_router)
app.include_router(finance_router)
app.include_router(notifications_router)

@app.get("/")
def health_check():
    return {"status": "healthy"}

# 5. Serve the single-file frontend prototype at /app  (same-origin → no CORS friction)
#    Looks in two locations so the same code works for local dev (project_root/frontend)
#    and the Docker layout where the frontend is COPY'd alongside `src/` at /app/frontend.
_FRONTEND_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "frontend",   # local: <repo>/frontend
    Path(__file__).resolve().parents[1] / "frontend",   # docker: /app/frontend
]
_FRONTEND_DIR = next((p for p in _FRONTEND_CANDIDATES if p.is_dir()), None)

# UI switch: /app/ serves either index-v2.html (v2, default on this branch) or index.html (v1).
# Opt out with ?ui=v1 — persists via cookie. Revert with ?ui=v2 or clear the cookie.
# Registered BEFORE the static mount so the explicit route wins at /app/.
if _FRONTEND_DIR is not None:
    @app.get("/app/", include_in_schema=False)
    @app.get("/app", include_in_schema=False)
    async def _serve_ui(request: Request):
        q = request.query_params.get("ui")
        cookie = request.cookies.get("taz_ui")
        which = q or cookie or "v2"
        if which not in ("v1", "v2"):
            which = "v2"
        target = _FRONTEND_DIR / ("index-v2.html" if which == "v2" else "index.html")
        if not target.is_file():
            target = _FRONTEND_DIR / "index.html"
            which = "v1"
        resp = FileResponse(target, media_type="text/html")
        resp.headers["Cache-Control"] = "no-cache"
        if q in ("v1", "v2"):
            resp.set_cookie("taz_ui", q, max_age=60 * 60 * 24 * 365, samesite="lax", path="/app/")
        return resp

    app.mount("/app", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="app")
