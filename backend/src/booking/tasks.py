# backend/src/booking/tasks.py
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .models import Booking
from ..inventory.models import Seat

async def cleanup_expired_bookings():
    """
    NFR-12 & SEAT-04: The Reaper background daemon.
    Scans every 60 seconds to automatically release seat holds from expired bookings.
    Handles both initial 'pending' locks and Phase 5 extended 'committed_pending' billing intents.
    """
    while True:
        db = SessionLocal()
        try:
            # Match python-naive timestamps used across models.py / service.py
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            
            # 1. Capture expired bookings across BOTH hold lifecycle phases
            expired_bookings = db.query(Booking).filter(
                Booking.status.in_(["pending", "committed_pending"]),
                Booking.expires_at < now_utc
            ).all()

            if expired_bookings:
                # Local import — avoids pulling the promo module into module
                # scope where it might affect the sanctified Reaper import graph.
                from ..promo.models import PromoCode

                for booking in expired_bookings:
                    # 2. Revert the physical Seat rows to 'available'
                    # seat_ids is tracked as an array of IDs inside our JSON column
                    if booking.seat_ids:
                        db.query(Seat).filter(
                            Seat.id.in_(booking.seat_ids),
                            Seat.trip_id == booking.trip_id
                        ).update({"status": "available"}, synchronize_session=False)

                    # 2.5. Release the reserved promo slot (reserve-at-lock,
                    # 2026-07-21). Only bookings that carried a promo_id
                    # incremented the counter at lock time, so we decrement
                    # here to keep max_redemptions exact for the next attempt.
                    if booking.promo_id:
                        promo = db.query(PromoCode).filter(PromoCode.id == booking.promo_id).first()
                        if promo and (promo.redemption_count or 0) > 0:
                            promo.redemption_count -= 1

                    # 3. Terminate the Booking record lifecycle state
                    booking.status = "expired"
                    print(f"REAPER: Released seats and marked Booking ID {booking.id} as expired ({booking.status})")

                # Commit all updates within an atomic batch execution block
                db.commit()
                
        except Exception as e:
            print(f"REAPER ERROR: {e}")
            db.rollback()
        finally:
            db.close()
        
        # Poll every 60 seconds
        await asyncio.sleep(60)
