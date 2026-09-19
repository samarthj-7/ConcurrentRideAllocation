from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class RiderCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str

class DriverCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str

class RideRequestCreate(BaseModel):
    rider_id: int
    pickup_lat: float
    pickup_lon: float
    dropoff_lat: float
    dropoff_lon: float

class DriverLocationUpdate(BaseModel):
    driver_id: int
    latitude: float
    longitude: float

class OfferResponse(BaseModel):
    offer_id: int
    request_id: int
    driver_id: int
    status: str

class RideRequestResponse(BaseModel):
    request_id: int
    rider_id: int
    status: str
    created_at: datetime
