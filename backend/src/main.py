import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import engine, Base
from .inventory.router import router as inventory_router
from .auth.router import router as auth_router
from .booking.router import router as booking_router
from .booking.tasks import cleanup_expired_bookings # <--- Import the task

# Ensure tables are created (Standard SQLAlchemy sync way)
Base.metadata.create_all(bind=engine)

# 1. Define the Lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: This runs when the server starts
    # We use asyncio.create_task so it runs in the background without blocking the API
    reaper_task = asyncio.create_task(cleanup_expired_bookings())
    
    yield  # The application serves requests here
    
    # SHUTDOWN: This runs when the server stops
    reaper_task.cancel()

# 2. Initialize FastAPI with the lifespan
app = FastAPI(
    title="Ticket Booking Platform API",
    lifespan=lifespan
)

# 3. Include Routers
app.include_router(inventory_router)
app.include_router(auth_router)
app.include_router(booking_router)

@app.get("/")
def health_check():
    return {"status": "healthy"}
