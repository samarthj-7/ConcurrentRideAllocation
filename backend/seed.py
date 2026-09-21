import psycopg
import random
import string
import time

DB_PARAMS = {
    "dbname": "ride_allocation",
    "user": "user",
    "password": "password",
    "host": "localhost",
    "port": 5435
}

def generate_random_string(length=10):
    return ''.join(random.choices(string.ascii_letters, k=length))

def generate_random_phone():
    return ''.join(random.choices(string.digits, k=10))

def generate_random_lat_lon():
    # Roughly continental US bounds
    lat = random.uniform(25.0, 49.0)
    lon = random.uniform(-125.0, -66.0)
    return round(lat, 6), round(lon, 6)

def seed_database(num_riders=1000, num_drivers=500, num_requests=100000):
    print(f"Connecting to database...")
    with psycopg.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            # 1. Insert Riders
            print(f"Inserting {num_riders} riders...")
            riders = [
                (f"Rider_{generate_random_string(5)}", 
                 f"{generate_random_string(8)}@example.com", 
                 generate_random_phone())
                for _ in range(num_riders)
            ]
            cur.executemany(
                "INSERT INTO rider (name, email, phone) VALUES (%s, %s, %s)",
                riders
            )

            # 2. Insert Drivers
            print(f"Inserting {num_drivers} drivers...")
            drivers = [
                (f"Driver_{generate_random_string(5)}", 
                 f"{generate_random_string(8)}@example.com", 
                 generate_random_phone(),
                 random.choice(['AVAILABLE', 'BUSY', 'OFFLINE']))
                for _ in range(num_drivers)
            ]
            cur.executemany(
                "INSERT INTO driver (name, email, phone, availability_status) VALUES (%s, %s, %s, %s)",
                drivers
            )

            # Retrieve IDs
            cur.execute("SELECT rider_id FROM rider LIMIT %s", (num_riders,))
            rider_ids = [r[0] for r in cur.fetchall()]
            
            cur.execute("SELECT driver_id FROM driver LIMIT %s", (num_drivers,))
            driver_ids = [r[0] for r in cur.fetchall()]

            # 3. Insert Requests in batches
            print(f"Inserting {num_requests} ride requests in batches...")
            batch_size = 5000
            for i in range(0, num_requests, batch_size):
                requests = []
                for _ in range(min(batch_size, num_requests - i)):
                    p_lat, p_lon = generate_random_lat_lon()
                    d_lat, d_lon = generate_random_lat_lon()
                    status = random.choice(['SEARCHING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'])
                    requests.append((
                        random.choice(rider_ids),
                        p_lat, p_lon, d_lat, d_lon, status
                    ))
                
                cur.executemany(
                    """INSERT INTO ride_request 
                       (rider_id, pickup_lat, pickup_lon, dropoff_lat, dropoff_lon, status) 
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    requests
                )
                print(f"  Inserted {i + len(requests)} / {num_requests}")
            
            # Commit changes
            conn.commit()
            print("Database seeded successfully!")

if __name__ == "__main__":
    start_time = time.time()
    # 100k rows is a good start for EXPLAIN plan differences
    seed_database(num_riders=1000, num_drivers=500, num_requests=100000)
    print(f"Finished in {time.time() - start_time:.2f} seconds.")
