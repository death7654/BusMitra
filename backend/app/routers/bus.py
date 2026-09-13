from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, UserPing
from ..schemas import BusStatusResponse
from ..services.crowd_aggregation import aggregate_bus_crowd


router = APIRouter(prefix="/api", tags=["Bus"])


@router.get("/bus/{bus_id}/status", response_model=BusStatusResponse)
def get_bus_status(
    bus_id: int,
    db: Session = Depends(get_db)
):
    # 1. Find the bus
    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail="Bus not found."
        )

    # 2. Get the latest GPS ping
    latest_ping = (
        db.query(UserPing)
        .filter(UserPing.bus_id == bus_id)
        .order_by(UserPing.timestamp.desc())
        .first()
    )

    # 3. Get crowd information from Phase 6
    crowd_data = aggregate_bus_crowd(
        db=db,
        bus_id=bus_id
    )

    # 4. Prepare latest location information
    if latest_ping is not None:
        latest_latitude = latest_ping.latitude
        latest_longitude = latest_ping.longitude
        latest_speed = latest_ping.speed
        latest_timestamp = latest_ping.timestamp
    else:
        latest_latitude = None
        latest_longitude = None
        latest_speed = None
        latest_timestamp = None

    # 5. Return combined bus status
    return BusStatusResponse(
        bus_id=bus.id,
        bus_number=bus.bus_number,
        route_id=bus.route_id,

        latest_latitude=latest_latitude,
        latest_longitude=latest_longitude,
        latest_speed=latest_speed,
        latest_timestamp=latest_timestamp,

        active_passengers=crowd_data["active_passengers"],
        passenger_fullness=crowd_data["passenger_fullness"],
        manual_fullness=crowd_data["manual_fullness"],
        overall_fullness=crowd_data["overall_fullness"],
        report_count=crowd_data["report_count"],
    )