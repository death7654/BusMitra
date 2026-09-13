from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, CheckIn, UserPing
from ..schemas import (
    CheckInRequest,
    CheckInResponse,
    PingRequest,
    PingResponse,
)
from ..services.bus_matching import match_user_to_bus


router = APIRouter(
    prefix="/api",
    tags=["Tracking"],
)


@router.post("/ping", response_model=PingResponse)
def receive_ping(
    ping: PingRequest,
    db: Session = Depends(get_db),
):
    """
    Receive a GPS ping from a user.

    Pings from users moving slower than 5 km/h
    are ignored for automatic bus matching.
    """

    # ---------------------------------------------------------
    # Ignore very slow users
    # ---------------------------------------------------------

    if ping.speed < 5:
        return PingResponse(
            accepted=False,
            matched=False,
            message="GPS ping ignored because speed is below 5 km/h.",
        )

    # ---------------------------------------------------------
    # Attempt bus matching
    # ---------------------------------------------------------

    result = match_user_to_bus(
        db=db,
        latitude=ping.latitude,
        longitude=ping.longitude,
    )

    bus = result["bus"]
    stop = result["stop"]
    distance = result["distance"]

    # ---------------------------------------------------------
    # Store GPS ping
    # ---------------------------------------------------------

    user_ping = UserPing(
        user_id=ping.user_id,
        latitude=ping.latitude,
        longitude=ping.longitude,
        speed=ping.speed,
        bus_id=bus.id if bus else None,
    )

    db.add(user_ping)
    db.commit()
    db.refresh(user_ping)

    # ---------------------------------------------------------
    # Return result
    # ---------------------------------------------------------

    return PingResponse(
        accepted=True,
        matched=result["matched"],
        bus_id=bus.id if bus else None,
        route_id=bus.route_id if bus else None,
        nearest_stop_id=stop.id if stop else None,
        distance_meters=round(distance, 2)
        if distance is not None
        else None,
        message=(
            "GPS ping stored and user matched to a bus."
            if bus
            else "GPS ping stored, but no bus match was found."
        ),
    )


@router.post("/checkin", response_model=CheckInResponse)
def check_in(
    checkin: CheckInRequest,
    db: Session = Depends(get_db),
):
    """
    Manually check a user into a bus.
    """

    # ---------------------------------------------------------
    # Verify that the bus exists
    # ---------------------------------------------------------

    bus = (
        db.query(Bus)
        .filter(Bus.id == checkin.bus_id)
        .first()
    )

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail="Bus not found.",
        )

    # ---------------------------------------------------------
    # Create check-in
    # ---------------------------------------------------------

    new_checkin = CheckIn(
        user_id=checkin.user_id,
        bus_id=checkin.bus_id,
    )

    db.add(new_checkin)
    db.commit()
    db.refresh(new_checkin)

    # ---------------------------------------------------------
    # Return result
    # ---------------------------------------------------------

    return CheckInResponse(
        success=True,
        user_id=checkin.user_id,
        bus_id=bus.id,
        bus_number=bus.bus_number,
        message="User successfully checked into the bus.",
    )