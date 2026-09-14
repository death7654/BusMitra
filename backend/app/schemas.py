from pydantic import BaseModel, Field
from datetime import datetime

class HealthResponse(BaseModel):
    status: str
    database: str


class PingRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed: float = Field(..., ge=0)


class PingResponse(BaseModel):
    accepted: bool
    matched: bool
    bus_id: int | None = None
    route_id: int | None = None
    nearest_stop_id: int | None = None
    distance_meters: float | None = None
    message: str

class CheckInRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    bus_id: int = Field(..., gt=0)


class CheckInResponse(BaseModel):
    success: bool
    user_id: int
    bus_id: int
    bus_number: str
    message: str

class CrowdReportRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    bus_id: int = Field(..., gt=0)
    crowd_level: int = Field(..., ge=1, le=5)


class CrowdReportResponse(BaseModel):
    success: bool
    user_id: int
    bus_id: int
    crowd_level: int
    message: str

class BusStatusResponse(BaseModel):
    bus_id: int
    bus_number: str
    route_id: int

    latest_latitude: float | None = None
    latest_longitude: float | None = None
    latest_speed: float | None = None
    latest_timestamp: datetime | None = None

    active_passengers: int
    passenger_fullness: float
    manual_fullness: float | None
    overall_fullness: float
    report_count: int

class BusPredictionResponse(BaseModel):
    bus_id: int
    stop_id: int
    hour_of_day: int
    day_of_week: int

    live_fullness: float
    predicted_fullness: float
    final_fullness: float

    status: str
    message: str


class RouteStopOut(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float


class RouteBusOut(BaseModel):
    id: int
    bus_number: str
    capacity: int


class RouteOut(BaseModel):
    route_id: int
    route_number: str
    route_name: str
    stops: list[RouteStopOut]
    buses: list[RouteBusOut]


class ForecastPoint(BaseModel):
    hour_of_day: int
    predicted_fullness: float


class ForecastDayPoint(BaseModel):
    day_of_week: int
    predicted_fullness: float


class BusForecastResponse(BaseModel):
    bus_id: int
    stop_id: int
    hourly: list[ForecastPoint]
    weekly: list[ForecastDayPoint]