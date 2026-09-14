from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, BusStop, Route
from ..schemas import (
    BusForecastResponse,
    ForecastDayPoint,
    ForecastPoint,
    RouteBusOut,
    RouteOut,
    RouteStopOut,
)
from ..services.prediction import predict_fullness


router = APIRouter(prefix="/api", tags=["Routes"])


@router.get("/routes", response_model=list[RouteOut])
def list_routes(db: Session = Depends(get_db)):
    """
    Real routes, named stops, and buses - for populating a journey
    search UI. Excludes the dense GPS-matching waypoint stops (their
    names contain " WP") since those exist only to make bus_matching
    work continuously along a route, not as places a rider would pick.
    """

    routes = db.query(Route).order_by(Route.id).all()

    result = []

    for route in routes:
        named_stops = [
            stop
            for stop in sorted(route.bus_stops, key=lambda s: s.id)
            if " WP" not in stop.name
        ]

        result.append(
            RouteOut(
                route_id=route.id,
                route_number=route.route_number,
                route_name=route.route_name,
                stops=[
                    RouteStopOut(
                        id=stop.id,
                        name=stop.name,
                        latitude=stop.latitude,
                        longitude=stop.longitude,
                    )
                    for stop in named_stops
                ],
                buses=[
                    RouteBusOut(
                        id=bus.id,
                        bus_number=bus.bus_number,
                        capacity=bus.capacity,
                    )
                    for bus in sorted(route.buses, key=lambda b: b.id)
                ],
            )
        )

    return result


@router.get("/bus/{bus_id}/forecast", response_model=BusForecastResponse)
def get_bus_forecast(
    bus_id: int,
    stop_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    Pure ML-model forecast for a bus/stop - no live data mixed in.

    hourly: predicted fullness for every hour of *today*, so a chart
    can show how crowding is expected to shift through the day.

    weekly: predicted fullness for every day of the week at the
    *current* hour, so a grid can show which days tend to run fuller.

    Both reuse the exact same RandomForestRegressor the live
    /prediction endpoint calls - nothing here is fabricated client-side
    math, unlike the original design mockup's history/forecast panels.
    """

    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

    from datetime import datetime

    now = datetime.now()

    hourly = [
        ForecastPoint(
            hour_of_day=hour,
            predicted_fullness=predict_fullness(
                bus_id=bus_id,
                stop_id=stop_id,
                hour_of_day=hour,
                day_of_week=now.weekday(),
            ),
        )
        for hour in range(24)
    ]

    weekly = [
        ForecastDayPoint(
            day_of_week=day,
            predicted_fullness=predict_fullness(
                bus_id=bus_id,
                stop_id=stop_id,
                hour_of_day=now.hour,
                day_of_week=day,
            ),
        )
        for day in range(7)
    ]

    return BusForecastResponse(
        bus_id=bus_id,
        stop_id=stop_id,
        hourly=hourly,
        weekly=weekly,
    )