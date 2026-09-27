from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, CheckIn, UserPing
from ..schemas import (
    CheckInRequest,
    CheckInResponse,
    CheckOutRequest,
    CheckOutResponse,
    PingRequest,
    PingResponse,
)
from ..services.bus_matching import match_user_to_bus
from ..services.crowd_aggregation import get_open_checkin


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
    # An open check-in overrides proximity matching
    # ---------------------------------------------------------
    #
    # If the rider has told us which bus they're on, believe them.
    # Proximity matching can pick the wrong vehicle when two routes
    # share a corridor, and silently re-attributing a rider mid-journey
    # makes both buses' crowd numbers wrong at once.

    open_checkin = get_open_checkin(db=db, user_id=ping.user_id)

    if open_checkin is not None:
        bus = db.query(Bus).filter(Bus.id == open_checkin.bus_id).first()
        stop = None
        distance = None
        matched = bus is not None
    else:
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
        matched = result["matched"]

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

    if bus and open_checkin is not None:
        message = "GPS ping stored against your checked-in bus."
    elif bus:
        message = "GPS ping stored and user matched to a bus."
    else:
        message = "GPS ping stored, but no bus match was found."

    return PingResponse(
        accepted=True,
        matched=matched,
        bus_id=bus.id if bus else None,
        route_id=bus.route_id if bus else None,
        nearest_stop_id=stop.id if stop else None,
        distance_meters=round(distance, 2)
        if distance is not None
        else None,
        message=message,
    )


@router.post("/checkin", response_model=CheckInResponse)
def check_in(
    checkin: CheckInRequest,
    db: Session = Depends(get_db),
):
    """
    Manually check a user into a bus.

    Check-ins are sessions, not events: the row stays open until the
    rider checks out. Re-sending a check-in for the same bus is a
    no-op rather than an error, so a retried request or a double tap
    can't make one person count as two riders.
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
    # Close any open check-in on a different bus
    # ---------------------------------------------------------
    #
    # Nobody rides two buses at once. Boarding a new one implicitly
    # ends the previous ride, which keeps the old bus's rider count
    # honest even when the user forgets to check out.

    existing = get_open_checkin(db=db, user_id=checkin.user_id)

    if existing is not None:
        if existing.bus_id == checkin.bus_id:
            return CheckInResponse(
                success=True,
                user_id=checkin.user_id,
                bus_id=bus.id,
                bus_number=bus.bus_number,
                message=(
                    f"Already checked in to {bus.bus_number}."
                ),
            )

        existing.checked_out_at = datetime.utcnow()

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


@router.post("/checkout", response_model=CheckOutResponse)
def check_out(
    checkout: CheckOutRequest,
    db: Session = Depends(get_db),
):
    """
    Check a user out of the bus they're currently riding.

    This closes the open check-in session, which removes the rider
    from the bus's active-passenger count straight away instead of
    waiting for the activity window to lapse.
    """

    open_checkin = get_open_checkin(
        db=db,
        user_id=checkout.user_id,
        bus_id=checkout.bus_id,
    )

    if open_checkin is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No open check-in found for this user"
                + (" on that bus." if checkout.bus_id else ".")
            ),
        )

    bus = (
        db.query(Bus)
        .filter(Bus.id == open_checkin.bus_id)
        .first()
    )

    if bus is None:
        # The bus was deleted while the rider was on it. Close the
        # session anyway - refusing would strand it open forever.
        open_checkin.checked_out_at = datetime.utcnow()
        db.commit()

        raise HTTPException(
            status_code=410,
            detail=(
                "That bus no longer exists. Your check-in "
                "has been closed."
            ),
        )

    checked_out_at = datetime.utcnow()
    open_checkin.checked_out_at = checked_out_at

    db.commit()
    db.refresh(open_checkin)

    ride_seconds = max(
        0,
        int((checked_out_at - open_checkin.timestamp).total_seconds()),
    )

    minutes = ride_seconds // 60

    return CheckOutResponse(
        success=True,
        user_id=open_checkin.user_id,
        bus_id=bus.id,
        bus_number=bus.bus_number,
        checked_in_at=open_checkin.timestamp,
        checked_out_at=checked_out_at,
        ride_seconds=ride_seconds,
        message=(
            f"Checked out of {bus.bus_number} after "
            f"{minutes} min. Thanks for the data!"
            if minutes >= 1
            else f"Checked out of {bus.bus_number}."
        ),
    )