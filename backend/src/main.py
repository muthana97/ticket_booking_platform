import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import settings
from .database import engine, Base
from .inventory.router import router as inventory_router
from .auth.router import router as auth_router
from .booking.router import router as booking_router
from .booking.tasks import cleanup_expired_bookings # <--- Import the task
from .admin.router import router as admin_router

# Ensure tables are created (Standard SQLAlchemy sync way)
Base.metadata.create_all(bind=engine)

def _bootstrap_if_empty():
    """
    Auto-seed on first boot. Render's free tier doesn't expose a shell, so
    `python seed.py` can't be run manually — we run it on startup instead,
    but only if the DB has no admin yet (idempotent across cold starts).
    """
    try:
        from .auth.models import User
        from .database import SessionLocal

        db = SessionLocal()
        has_admin = db.query(User).filter(User.role == "admin").first() is not None
        db.close()

        if has_admin:
            print("[BOOTSTRAP] admin present — skipping seed")
            return

        print("[BOOTSTRAP] empty DB — running seed_data()")
        from seed import seed_data
        seed_data()
    except Exception as e:
        print(f"[BOOTSTRAP] failed: {e!r}")


# 1. Define the Lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
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
if _FRONTEND_DIR is not None:
    app.mount("/app", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="app")
