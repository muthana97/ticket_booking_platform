from src.database import SessionLocal
from src.inventory.models import Route, Bus, Trip, Seat
from src.auth.models import User 
from datetime import datetime, timedelta

def seed_data():
    db = SessionLocal()
    try:
        # 1. Setup a Test User (For linking to Bookings later)
        test_user = User(phone_number="249123456789", full_name="Test Customer")
        db.add(test_user)
        db.flush()

        # 2. Setup a Route (A-RTE-02)
        route = Route(origin="Khartoum", destination="Port Sudan", distance=800, duration="12h")
        db.add(route)
        db.flush()

        # 3. Setup a Bus with a 2x2 Layout (P-TRIP-04)
        bus = Bus(
            provider_id=1, 
            total_seats=4,
            seat_layout_config={"rows": 1, "cols": 4, "naming": ["1A", "1B", "1C", "1D"]}
        )
        db.add(bus)
        db.flush()

        # 4. Create the Trip (SRCH-02)
        trip = Trip(
            route_id=route.id,
            bus_id=bus.id,
            departure_time=datetime.utcnow() + timedelta(days=1),
            price=15000.0
        )
        db.add(trip)
        db.flush()

        # 5. Generate Physical Seats (SEAT-01)
        seat_names = ["1A", "1B", "1C", "1D"]
        for name in seat_names:
            db.add(Seat(trip_id=trip.id, seat_number=name, status="available"))

        db.commit()
        print("✅ Success: Phase 3 Data Seeded. You now have a Trip and 4 available Seats.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error during seeding: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
