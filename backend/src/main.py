from fastapi import FastAPI
from .database import engine, Base
from .inventory.router import router as inventory_router
from .auth.router import router as auth_router  # <--- Add this
from .booking.router import router as booking_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ticket Booking Platform API")

# Include Routers
app.include_router(inventory_router)
app.include_router(auth_router)  # <--- Add this
app.include_router(booking_router)  # <--- Register the hot path

@app.get("/")
def health_check():
    return {"status": "healthy"}
