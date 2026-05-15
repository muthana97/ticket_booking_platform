import threading
import requests
import json

# --- Configuration ---
API_URL = "http://127.0.0.1:8000/bookings/lock"
# Get a real JWT token by logging in via your /auth/ routes first
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzIiwiZXhwIjoxNzc4OTQ4NTU5fQ.MUBrqHwVlw80N2DIzDBpbHtoOYBkyvliT35kTS0KSsM" 
TRIP_ID = 1  # Assuming this is the ID from your seed.py
SEAT_NUMBERS = ["1A"]

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

payload = {
    "trip_id": TRIP_ID,
    "seat_numbers": SEAT_NUMBERS
}

def attempt_booking(user_label):
    print(f"[User {user_label}] Sending lock request...")
    response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
    print(f"[User {user_label}] Status: {response.status_code} | Response: {response.text}")

# Simulate two users clicking 'Book' at the exact same time
if __name__ == "__main__":
    t1 = threading.Thread(target=attempt_booking, args=("A",))
    t2 = threading.Thread(target=attempt_booking, args=("B",))

    t1.start()
    t2.start()

    t1.join()
    t2.join()
