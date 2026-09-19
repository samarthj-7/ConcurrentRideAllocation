import pytest
import requests
import threading
import time
import random
import psycopg
from backend.db import DATABASE_URL

API_URL = "http://localhost:8088"

def clean_database():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE ride_request CASCADE")
            cur.execute("TRUNCATE TABLE driver CASCADE")
            cur.execute("TRUNCATE TABLE rider CASCADE")
        conn.commit()

@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    clean_database()
    yield
    clean_database()

def test_concurrent_ride_acceptance():
    """
    Test that when 10 drivers try to accept the same ride request at exactly the same time,
    only 1 succeeds, and the database remains consistent (only 1 assignment).
    """
    # 1. Create a rider
    rider_res = requests.post(f"{API_URL}/riders/", json={
        "name": "Test Rider",
        "email": f"rider{random.randint(1,10000)}@test.com",
        "phone": f"555-{random.randint(1000,9999)}"
    })
    rider_id = rider_res.json()["rider_id"]

    # 2. Create 10 drivers
    driver_ids = []
    for i in range(10):
        driver_res = requests.post(f"{API_URL}/drivers/", json={
            "name": f"Driver {i}",
            "email": f"driver{i}_{random.randint(1,10000)}@test.com",
            "phone": f"555-D{random.randint(1000,9999)}"
        })
        driver_ids.append(driver_res.json()["driver_id"])

    # 3. Create a ride request
    req_res = requests.post(f"{API_URL}/requests/", json={
        "rider_id": rider_id,
        "pickup_lat": 10.0, "pickup_lon": 10.0,
        "dropoff_lat": 20.0, "dropoff_lon": 20.0
    })
    request_id = req_res.json()["request_id"]
    
    # 4. Fetch the offer ID for each driver (Polling)
    offers = []
    for i in range(10): # 10 retries (5 seconds)
        offers = []
        for d_id in driver_ids:
            offers_res = requests.get(f"{API_URL}/drivers/{d_id}/offers")
            offer_data = offers_res.json()
            if offer_data:
                offers.append(offer_data[0]["offer_id"])
        if len(offers) == 10:
            break
        time.sleep(0.5)

    assert len(offers) == 10, f"Not all drivers received an offer, got {len(offers)}"

    # 5. Concurrent Accept
    success_count = 0
    conflict_count = 0
    error_count = 0

    def accept_offer(offer_id):
        nonlocal success_count, conflict_count, error_count
        res = requests.post(f"{API_URL}/offers/{offer_id}/accept")
        if res.status_code == 200:
            success_count += 1
        elif res.status_code in (409, 400):
            conflict_count += 1
        else:
            error_count += 1

    threads = []
    for offer_id in offers:
        t = threading.Thread(target=accept_offer, args=(offer_id,))
        threads.append(t)

    # Start all threads at roughly the same time
    for t in threads:
        t.start()

    # Wait for all threads to finish
    for t in threads:
        t.join()

    # 6. Assertions
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
    assert conflict_count == 9, f"Expected exactly 9 conflicts, got {conflict_count}"
    assert error_count == 0, f"Expected 0 errors, got {error_count}"

    # 7. Database Invariant Check
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # Check exactly 1 assignment exists for this request
            cur.execute("SELECT count(*) FROM assignment WHERE request_id = %s", (request_id,))
            assignment_count = cur.fetchone()[0]
            assert assignment_count == 1, f"Database invariant violated! Expected 1 assignment, found {assignment_count}"
            
            # Check request status is ASSIGNED
            cur.execute("SELECT status FROM ride_request WHERE request_id = %s", (request_id,))
            req_status = cur.fetchone()[0]
            assert req_status == 'ASSIGNED'
