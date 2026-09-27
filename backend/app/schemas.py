import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

class HealthResponse(BaseModel):
    status: str
    database: str
    demo_mode: bool = False


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


class CheckOutRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    # Optional: when omitted the rider is checked out of whichever bus
    # they currently have an open check-in on. A rider can only be on
    # one bus at a time, so this is unambiguous.
    bus_id: int | None = Field(default=None, gt=0)


class CheckOutResponse(BaseModel):
    success: bool
    user_id: int
    bus_id: int
    bus_number: str
    checked_in_at: datetime
    checked_out_at: datetime
    ride_seconds: int
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

    # Returned so the reporter immediately sees their contribution
    # land, rather than tapping into a void and hoping.
    overall_fullness: float | None = None
    reporter_count: int = 0
    replaced_previous: bool = False
    next_report_in_seconds: int = 0

class OutageReportRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    bus_id: int = Field(..., gt=0)
    reason: str = Field(default="not_running")

    @field_validator("reason")
    @classmethod
    def normalise_reason(cls, value: str) -> str:
        allowed = {"not_running", "breakdown", "never_arrived", "accident", "other"}
        cleaned = (value or "not_running").strip().lower()
        return cleaned if cleaned in allowed else "other"


class OutageStatus(BaseModel):
    """
    Whether a bus currently reads as reported out of service, and by
    how much. Embedded in BusStatusResponse and BatchBusState rather
    than fetched separately, so a client already polling for crowd
    figures gets this for free.
    """

    reported_out_of_service: bool = False
    outage_report_count: int = 0
    outage_reasons: list[str] = []
    last_outage_report_at: datetime | None = None


class OutageReportResponse(BaseModel):
    success: bool
    user_id: int
    bus_id: int
    reason: str
    message: str
    status: OutageStatus


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

    # How the overall figure was arrived at, so the UI can be honest
    # about whether it's showing a headcount, riders' own reports, or
    # a blend - and how much evidence sits behind each.
    reporter_count: int = 0
    passenger_weight: float = 0.0
    report_weight: float = 0.0
    crowd_source: str = "none"
    trend: str = "unknown"

    outage: OutageStatus = OutageStatus()


class WeatherResponse(BaseModel):
    latitude: float
    longitude: float
    temperature_c: float | None = None
    precipitation_mm: float = 0.0
    wind_speed_kmh: float | None = None
    # "clear" | "clouds" | "fog" | "rain" | "snow" | "storm" | "unknown"
    condition: str = "Unknown"
    condition_category: str = "unknown"
    # Plain-language note when the weather is likely to affect service,
    # e.g. heavier crowding or slower buses. None in ordinary weather.
    advisory: str | None = None
    observed_at: str | None = None

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

    # How the two halves were weighted, and how much to trust the
    # result. The blend is no longer a fixed 60/40: the live half only
    # earns its share when there is evidence behind it, so these have
    # to be reported rather than assumed by the client.
    live_weight: float = 0.0
    model_weight: float = 1.0
    live_evidence: float = 0.0
    confidence: str = "model_only"
    observed_samples: int = 0
    explanation: str = ""


class ObservationSummary(BaseModel):
    real_observations: int
    simulated_observations: int
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    sample_interval_seconds: int
    min_evidence: float


class ModelInfoResponse(BaseModel):
    """
    Provenance for the forecast half of every number in the app.

    Exists so "our model learns from real usage" is a claim anyone can
    check from a browser, rather than one they have to take on trust.
    """

    available: bool
    model_path: str
    features: list[str] = []

    trained_at: datetime | None = None
    trained_on: str = "unknown"
    synthetic_rows: int = 0
    real_rows: int = 0
    real_row_share: float = 0.0

    mae: float | None = None
    rmse: float | None = None
    r2: float | None = None

    observations: ObservationSummary
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


# ---------------------------------------------------------
# Bus administration (create / list / delete)
# ---------------------------------------------------------

# Fleet numbers are short, human-readable plate-style identifiers.
# Anything outside this shape is almost certainly a typo or a paste
# accident, and letting it through would put unusable labels on the
# map that only another admin call could remove.
BUS_NUMBER_PATTERN = r"^[A-Z0-9][A-Z0-9 \-]{1,19}$"


class BusCreateRequest(BaseModel):
    route_id: int = Field(..., gt=0)
    bus_number: str = Field(..., min_length=2, max_length=20)
    capacity: int = Field(..., gt=0, le=300)

    @field_validator("bus_number")
    @classmethod
    def normalise_bus_number(cls, value: str) -> str:
        """
        Upper-case and collapse whitespace before the uniqueness check,
        so "bus-101-a" and "BUS-101-A " can't both exist as separate
        rows that look identical in the UI.
        """

        cleaned = " ".join(value.strip().upper().split())

        if not re.match(BUS_NUMBER_PATTERN, cleaned):
            raise ValueError(
                "Bus number must be 2-20 characters using only "
                "letters, digits, spaces and hyphens."
            )

        return cleaned


class BusOut(BaseModel):
    id: int
    bus_number: str
    capacity: int
    route_id: int
    route_number: str
    route_name: str
    active_passengers: int = 0


class BusDeleteResponse(BaseModel):
    success: bool
    bus_id: int
    bus_number: str
    deleted_pings: int
    deleted_checkins: int
    deleted_reports: int
    message: str


class BusDependencyCounts(BaseModel):
    pings: int
    checkins: int
    reports: int


# ---------------------------------------------------------
# Demo mode
# ---------------------------------------------------------

class DemoBusState(BaseModel):
    bus_id: int
    bus_number: str
    latitude: float
    longitude: float
    speed_kmh: float
    simulated_riders: int
    capacity: int


class DemoStatusResponse(BaseModel):
    available: bool
    running: bool
    started_at: datetime | None = None
    ticks: int = 0
    tick_seconds: float
    simulated_buses: list[DemoBusState] = []
    message: str


class DemoResetResponse(BaseModel):
    success: bool
    deleted_pings: int
    deleted_checkins: int
    deleted_reports: int
    message: str


# ---------------------------------------------------------
# Arrivals
# ---------------------------------------------------------

class EtaResponse(BaseModel):
    bus_id: int
    stop_id: int

    status: str
    message: str

    eta_seconds: int | None = None
    eta_minutes: float | None = None
    # Upper end of the range when the route's geometry leaves genuine
    # doubt about which pass the bus is on.
    eta_max_seconds: int | None = None

    distance_meters: float | None = None
    straight_line_meters: float | None = None
    speed_kmh: float | None = None
    stops_away: int | None = None
    off_route_meters: float | None = None

    sample_count: int = 0
    confidence: str = "none"

    # Lower end of the plausible range. Derived from the Kalman
    # filter's own velocity covariance rather than a flat percentage,
    # so the width of the band is evidence about this bus at this
    # moment. eta_seconds remains the single best guess.
    eta_min_seconds: int | None = None

    # Standard deviation of the filtered velocity, m/s. Small means the
    # bus has been travelling predictably; large means the estimate is
    # riding on very little.
    velocity_std_ms: float | None = None

    # Fraction of the road ahead costed from recorded history rather
    # than from the bus's current speed, 0.0-1.0.
    learned_traffic_share: float = 0.0

    # Seconds charged per intermediate stop, scaled by how full the bus
    # is. Surfaced so a long ETA on a packed bus is explicable.
    dwell_seconds: float | None = None


class StopArrival(BaseModel):
    bus_id: int
    bus_number: str
    route_id: int
    route_number: str
    route_name: str

    eta: EtaResponse

    overall_fullness: float
    crowd_source: str
    trend: str
    active_passengers: int
    reporter_count: int
    capacity: int


class StopBoardResponse(BaseModel):
    stop_id: int
    stop_name: str
    generated_at: datetime
    arrivals: list[StopArrival]
    message: str

# ---------------------------------------------------------
# Batch fleet status
# ---------------------------------------------------------

class BatchBusState(BaseModel):
    """
    One bus's complete current state.

    A union of what /bus/{id}/status, /bus/{id}/prediction and
    /bus/{id}/eta each returned separately. Field names match those
    endpoints exactly so a client can switch to the batch call without
    rewriting how it reads a bus.
    """

    bus_id: int
    bus_number: str
    route_id: int
    capacity: int

    latest_latitude: float | None = None
    latest_longitude: float | None = None
    latest_speed: float | None = None
    latest_timestamp: datetime | None = None

    active_passengers: int
    passenger_fullness: float
    manual_fullness: float | None
    overall_fullness: float
    report_count: int
    reporter_count: int = 0
    passenger_weight: float = 0.0
    report_weight: float = 0.0
    crowd_source: str = "none"
    trend: str = "unknown"

    outage: OutageStatus = OutageStatus()

    # Both absent when the request named no stop, since neither an
    # arrival nor a stop-specific prediction means anything without one.
    eta: EtaResponse | None = None
    prediction: BusPredictionResponse | None = None


class BatchStatusResponse(BaseModel):
    generated_at: datetime
    stop_id: int | None = None
    buses: list[BatchBusState]

    # Ids the caller asked for that no longer exist. Reported rather
    # than 404ing the batch, so one stale id can't blank a whole screen.
    missing_bus_ids: list[int] = []


# ---------------------------------------------------------
# Journey planning
# ---------------------------------------------------------

class JourneyLegOut(BaseModel):
    route_id: int
    route_number: str
    route_name: str

    board_stop_id: int
    board_stop_name: str
    alight_stop_id: int
    alight_stop_name: str

    stops_count: int
    bus_ids: list[int] = []

    # Only populated for the first leg. The connecting bus you will
    # actually catch is not the one approaching that stop now, so
    # quoting a live arrival for a later leg would be a confident
    # answer to a question nobody asked.
    best_bus_id: int | None = None
    best_bus_number: str | None = None
    eta_seconds: int | None = None
    eta_status: str = "no_data"
    overall_fullness: float | None = None


class JourneyOption(BaseModel):
    legs: list[JourneyLegOut]
    transfers: int
    total_stops: int

    first_departure_seconds: int | None = None

    # Lower is better. Waiting plus riding plus a penalty per change;
    # exposed so the ordering is inspectable rather than magic.
    score: float


class JourneyPlanResponse(BaseModel):
    from_stop: str
    to_stop: str
    generated_at: datetime
    options: list[JourneyOption]
    message: str


# ---------------------------------------------------------
# Calibration
# ---------------------------------------------------------

class CalibrationBucket(BaseModel):
    confidence: str
    samples: int

    mean_absolute_error: float | None = None

    # Signed mean error. Distinguishes a model that is consistently
    # high from one that is merely noisy - noise averages to zero here,
    # bias doesn't.
    bias: float | None = None

    within_10_points: float | None = None
    within_20_points: float | None = None


class CalibrationResponse(BaseModel):
    days: int
    total_scored: int
    buckets: list[CalibrationBucket]
    overall_mae: float | None = None
    overall_bias: float | None = None
    message: str
