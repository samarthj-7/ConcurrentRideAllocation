import psycopg_pool
from contextlib import contextmanager

# Hardcoded for local testing per docker-compose
DATABASE_URL = "postgres://user:password@localhost:5435/ride_allocation"

# Create a connection pool
# Note: In production, configure min/max sizes based on workload.
pool = psycopg_pool.ConnectionPool(DATABASE_URL, min_size=5, max_size=20)

@contextmanager
def get_db_connection():
    """
    Dependency to get a database connection from the pool.
    Usage:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    with pool.connection() as conn:
        yield conn
