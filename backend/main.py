import json
import logging
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import psycopg
from psycopg.errors import UniqueViolation, CheckViolation, SerializationFailure
import threading
from fastapi.responses import JSONResponse

from .db import get_db_connection
from .models import (
    RiderCreate, DriverCreate, RideRequestCreate,
    DriverLocationUpdate
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Concurrent Ride Allocation System")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates setup for frontend
templates = Jinja2Templates(directory="frontend")

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        # Maps driver_id to WebSocket
        self.active_drivers: dict[int, WebSocket] = {}
        # Maps rider_id to WebSocket
        self.active_riders: dict[int, WebSocket] = {}
        # List of connected admins
        self.active_admins: list[WebSocket] = []
        self.lock = threading.Lock()

    async def connect_driver(self, websocket: WebSocket, driver_id: int):
        await websocket.accept()
        with self.lock:
            self.active_drivers[driver_id] = websocket
        logger.info(f"Driver {driver_id} connected")

    def disconnect_driver(self, driver_id: int):
        with self.lock:
            if driver_id in self.active_drivers:
                del self.active_drivers[driver_id]
        logger.info(f"Driver {driver_id} disconnected")

    async def connect_rider(self, websocket: WebSocket, rider_id: int):
        await websocket.accept()
        with self.lock:
            self.active_riders[rider_id] = websocket
        logger.info(f"Rider {rider_id} connected")

    def disconnect_rider(self, rider_id: int):
        with self.lock:
            if rider_id in self.active_riders:
                del self.active_riders[rider_id]
        logger.info(f"Rider {rider_id} disconnected")

    async def connect_admin(self, websocket: WebSocket):
        await websocket.accept()
        with self.lock:
            self.active_admins.append(websocket)
        logger.info("Admin connected")

    def disconnect_admin(self, websocket: WebSocket):
        with self.lock:
            if websocket in self.active_admins:
                self.active_admins.remove(websocket)
        logger.info("Admin disconnected")

    async def send_to_driver(self, driver_id: int, message: dict):
        with self.lock:
            ws = self.active_drivers.get(driver_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to driver {driver_id}: {e}")

    async def send_to_rider(self, rider_id: int, message: dict):
        with self.lock:
            ws = self.active_riders.get(rider_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to rider {rider_id}: {e}")

    async def broadcast_to_admins(self, message: dict):
        with self.lock:
            websockets = self.active_admins.copy()
        
        for ws in websockets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to admin: {e}")
                self.disconnect_admin(ws)

manager = ConnectionManager()

# --- FRONTEND ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/rider-dashboard", response_class=HTMLResponse)
async def rider_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="rider.html")

@app.get("/driver-dashboard", response_class=HTMLResponse)
async def driver_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="driver.html")

@app.get("/admin-dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html")

# --- API ROUTES ---

@app.post("/riders/")
def create_rider(rider: RiderCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO rider (name, email, phone) VALUES (%s, %s, %s) RETURNING rider_id",
                    (rider.name, rider.email, rider.phone)
                )
                rider_id = cur.fetchone()[0]
                conn.commit()
                return {"rider_id": rider_id, "message": "Rider created"}
            except UniqueViolation:
                conn.rollback()
                raise HTTPException(status_code=400, detail="Email or phone already exists")

@app.post("/drivers/")
def create_driver(driver: DriverCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO driver (name, email, phone, availability_status) VALUES (%s, %s, %s, 'AVAILABLE') RETURNING driver_id",
                    (driver.name, driver.email, driver.phone)
                )
                driver_id = cur.fetchone()[0]
                conn.commit()
                return {"driver_id": driver_id, "message": "Driver created"}
            except UniqueViolation:
                conn.rollback()
                raise HTTPException(status_code=400, detail="Email or phone already exists")

@app.post("/requests/")
async def create_ride_request(request: RideRequestCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Create request
            cur.execute(
                """INSERT INTO ride_request (rider_id, pickup_lat, pickup_lon, dropoff_lat, dropoff_lon, status)
                   VALUES (%s, %s, %s, %s, %s, 'SEARCHING') RETURNING request_id""",
                (request.rider_id, request.pickup_lat, request.pickup_lon, request.dropoff_lat, request.dropoff_lon)
            )
            request_id = cur.fetchone()[0]
            
            # Find all available drivers
            cur.execute("SELECT driver_id FROM driver WHERE availability_status = 'AVAILABLE'")
            available_drivers = cur.fetchall()

            # Create offers for them
            for (d_id,) in available_drivers:
                cur.execute(
                    "INSERT INTO ride_offer (request_id, driver_id, status) VALUES (%s, %s, 'PENDING') RETURNING offer_id",
                    (request_id, d_id)
                )
                offer_id = cur.fetchone()[0]
                
                # Notify driver via websocket (we don't wait for it to commit to send, but in real app, better after commit)
                # We will send a generic offer message
            
            conn.commit()
    
    # Send WebSocket messages after transaction commit
    for (d_id,) in available_drivers:
        # We need the offer_id, let's fetch it again or store it in memory.
        # For simplicity, we just send a "new_offer" event and driver fetches pending offers.
        await manager.send_to_driver(d_id, {"type": "new_offer", "request_id": request_id})

    # Broadcast to admins
    await manager.broadcast_to_admins({
        "type": "ride_created",
        "request_id": request_id,
        "rider_id": request.rider_id,
        "pickup": [request.pickup_lat, request.pickup_lon],
        "dropoff": [request.dropoff_lat, request.dropoff_lon],
        "status": "SEARCHING"
    })

    return {"request_id": request_id, "message": "Ride request created, looking for drivers."}

@app.get("/drivers/{driver_id}/offers")
def get_driver_offers(driver_id: int):
    """Fetch pending offers for a driver"""
    with get_db_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("""
                SELECT o.offer_id, o.request_id, r.pickup_lat, r.pickup_lon, r.dropoff_lat, r.dropoff_lon
                FROM ride_offer o
                JOIN ride_request r ON o.request_id = r.request_id
                WHERE o.driver_id = %s AND o.status = 'PENDING' AND r.status = 'SEARCHING'
            """, (driver_id,))
            offers = cur.fetchall()
            return offers

@app.get("/admin/rides")
def get_all_rides():
    """Fetch all rides for the admin dashboard"""
    with get_db_connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("""
                SELECT 
                    r.request_id, 
                    r.rider_id, 
                    r.status, 
                    r.pickup_lat, r.pickup_lon, 
                    r.dropoff_lat, r.dropoff_lon,
                    a.driver_id
                FROM ride_request r
                LEFT JOIN assignment a ON r.request_id = a.request_id
                ORDER BY r.created_at DESC
            """)
            rides = cur.fetchall()
            return rides


# --- THE CORE CONCURRENCY ENDPOINT ---
@app.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: int):
    """
    Accept an offer. This endpoint handles concurrency by using database-level row locks (SELECT ... FOR UPDATE).
    Multiple drivers can hit this endpoint concurrently for the same request.
    Only one driver will successfully update the request status and insert an assignment.
    """
    with get_db_connection() as conn:
        # Start an explicit transaction block
        with conn.transaction():
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                # 1. Get the offer details
                cur.execute("SELECT request_id, driver_id, status FROM ride_offer WHERE offer_id = %s", (offer_id,))
                offer = cur.fetchone()
                if not offer:
                    raise HTTPException(status_code=404, detail="Offer not found")
                if offer['status'] != 'PENDING':
                    raise HTTPException(status_code=400, detail="Offer is no longer pending")

                request_id = offer['request_id']
                driver_id = offer['driver_id']

                # 2. LOCK THE RIDE REQUEST ROW
                # This prevents other concurrent transactions from modifying this request until we commit or rollback.
                cur.execute("SELECT status, rider_id FROM ride_request WHERE request_id = %s FOR UPDATE", (request_id,))
                req = cur.fetchone()

                if not req:
                    raise HTTPException(status_code=404, detail="Ride request not found")

                # 3. Check if the ride has already been assigned
                if req['status'] != 'SEARCHING':
                    # Another driver has already accepted it (or it was cancelled).
                    # Update our local offer to rejected/expired.
                    cur.execute("UPDATE ride_offer SET status = 'EXPIRED' WHERE offer_id = %s", (offer_id,))
                
                    # Cannot use HTTPException inside a transaction block if we want the UPDATE to commit.
                    # Instead, we set a flag and handle it outside, or just return JSONResponse.
                    # Wait, if we return from here, the transaction block exits normally and commits!
                    return JSONResponse(status_code=409, content={"detail": "Ride request is no longer available (already assigned or cancelled)."})

                # 4. Proceed with Assignment
                # Mark request as ASSIGNED
                cur.execute("UPDATE ride_request SET status = 'ASSIGNED' WHERE request_id = %s", (request_id,))
                
                # Mark offer as ACCEPTED
                cur.execute("UPDATE ride_offer SET status = 'ACCEPTED' WHERE offer_id = %s", (offer_id,))
                
                # Mark all other offers for this request as EXPIRED
                cur.execute("UPDATE ride_offer SET status = 'EXPIRED' WHERE request_id = %s AND offer_id != %s", (request_id, offer_id))
                
                # Insert the Assignment
                cur.execute("INSERT INTO assignment (request_id, driver_id) VALUES (%s, %s)", (request_id, driver_id))
                
                # Update driver availability
                cur.execute("UPDATE driver SET availability_status = 'BUSY' WHERE driver_id = %s", (driver_id,))
                
                rider_id = req['rider_id']

    # Transaction is committed at this point automatically by psycopg's `with conn.transaction()` block upon successful exit.

    # Notify Rider
    await manager.send_to_rider(rider_id, {
        "type": "ride_assigned",
        "request_id": request_id,
        "driver_id": driver_id,
        "message": f"Driver {driver_id} has accepted your ride!"
    })

    # Notify Admins
    await manager.broadcast_to_admins({
        "type": "ride_assigned",
        "request_id": request_id,
        "driver_id": driver_id,
        "status": "ASSIGNED"
    })

    return {"message": "Offer accepted successfully", "request_id": request_id, "driver_id": driver_id}


# --- WEBSOCKET ENDPOINTS ---
@app.websocket("/ws/driver/{driver_id}")
async def websocket_driver_endpoint(websocket: WebSocket, driver_id: int):
    await manager.connect_driver(websocket, driver_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages from driver (e.g., location updates)
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_driver(driver_id)

@app.websocket("/ws/rider/{rider_id}")
async def websocket_rider_endpoint(websocket: WebSocket, rider_id: int):
    await manager.connect_rider(websocket, rider_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_rider(rider_id)

@app.websocket("/ws/admin")
async def websocket_admin_endpoint(websocket: WebSocket):
    await manager.connect_admin(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect_admin(websocket)

