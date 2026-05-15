# backend/src/booking/tasks.py
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .models import Booking
from ..inventory.models import Seat

async def cleanup_expired_bookings():
    """
    NFR-12: Background task to release seats from expired bookings.
    Runs every 60 seconds.
    """
    while True:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            # 1. Find all pending bookings that have passed their expiry time
            expired_bookings = db.query(Booking).filter(
                Booking.status == "pending",
                Booking.expires_at < now
            ).all()

            for booking in expired_bookings:
                # 2. Revert Seat status to 'available'
                # seat_ids is stored as a list in a JSON column
                db.query(Seat).filter(
                    Seat.id.in_(booking.seat_ids),
                    Seat.trip_id == booking.trip_id
                ).update({"status": "available"}, synchronize_session=False)

                # 3. Mark Booking as 'expired'
                booking.status = "expired"
                print(f"REAPER: Released seats for Booking ID {booking.id}")

            db.commit()
        except Exception as e:
            print(f"REAPER ERROR: {e}")
            db.rollback()
        finally:
            db.close()
        
        # Run check every minute
        await asyncio.sleep(60)
