from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BusStop
from ..schemas import WeatherResponse
from ..services.weather import get_weather


router = APIRouter(prefix="/api", tags=["Weather"])


@router.get("/weather", response_model=WeatherResponse)
async def weather(
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    db: Session = Depends(get_db),
):
    """
    Current weather for a rider's position, or the service area.

    Falls back to the first bus stop on file when the caller has no
    GPS fix yet (or hasn't granted location permission), so the
    Predict page can show conditions before tracking has ever started.
    """

    if latitude is None or longitude is None:
        stop = db.query(BusStop).first()

        if stop is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No coordinates given and no bus stops on file to "
                    "fall back to."
                ),
            )

        latitude, longitude = stop.latitude, stop.longitude

    try:
        data = await get_weather(latitude, longitude)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the weather service: {exc}",
        )

    return WeatherResponse(**data)
