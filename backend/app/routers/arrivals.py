from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, BusStop
from ..schemas import EtaResponse, StopArrival, StopBoardResponse
from ..services.crowd_aggregation import aggregate_bus_crowd
from ..services.eta import estimate_arrival


router = APIRouter(prefix="/api", tags=["Arrivals"])


# Statuses that represent a bus genuinely on its way here. Anything
# else is either not coming or not knowable, and mixing the two into
# one list is how a board becomes untrustworthy.
APPROACHING = {"approaching", "uncertain"}


def _eta_response(bus_id: int, stop_id: int, data: dict) -> EtaResponse:
    return EtaResponse(bus_id=bus_id, stop_id=stop_id, **data)


@router.get("/bus/{bus_id}/eta", response_model=EtaResponse)
def get_bus_eta(
    bus_id: int,
    stop_id: int,
    db: Session = Depends(get_db),
):
    """
    When this bus reaches this stop, measured along the actual route.

    See services/eta.py for why this isn't straight-line distance over
    reported speed.
    """

    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()

    if stop is None:
        raise HTTPException(status_code=404, detail="Stop not found.")

    return _eta_response(
        bus_id, stop_id, estimate_arrival(db=db, bus=bus, stop=stop)
    )


@router.get("/stop/{stop_id}/arrivals", response_model=StopBoardResponse)
def get_stop_board(
    stop_id: int,
    include_unknown: bool = Query(
        default=False,
        description=(
            "Include buses whose arrival can't currently be estimated "
            "(no live position, stopped, or already past)."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    A live departure board for one stop.

    This is the question a rider standing at a stop actually has -
    "what's coming, when, and will I get a seat" - answered in one
    call. It's the same data the Predict page uses, reorganised around
    the stop rather than around a journey, and it only exists usefully
    because the ETA is now route-aware: a board built on straight-line
    distance would happily list a bus that had already driven past.
    """

    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()

    if stop is None:
        raise HTTPException(status_code=404, detail="Stop not found.")

    buses = (
        db.query(Bus)
        .filter(Bus.route_id == stop.route_id)
        .order_by(Bus.id)
        .all()
    )

    arrivals: list[StopArrival] = []

    for bus in buses:
        # Crowd first: it feeds the dwell model, so a packed bus is
        # charged the longer boarding time it actually takes. Computing
        # the ETA first and the crowd afterwards would silently fall
        # back to the neutral dwell figure for every bus on the board.
        crowd = aggregate_bus_crowd(db=db, bus_id=bus.id)

        eta = estimate_arrival(
            db=db,
            bus=bus,
            stop=stop,
            occupancy_pct=crowd["overall_fullness"],
        )

        if eta["status"] not in APPROACHING and not include_unknown:
            continue

        arrivals.append(
            StopArrival(
                bus_id=bus.id,
                bus_number=bus.bus_number,
                route_id=bus.route_id,
                route_number=bus.route.route_number,
                route_name=bus.route.route_name,
                eta=_eta_response(bus.id, stop_id, eta),
                overall_fullness=crowd["overall_fullness"],
                crowd_source=crowd["crowd_source"],
                trend=crowd["trend"],
                active_passengers=crowd["active_passengers"],
                reporter_count=crowd["reporter_count"],
                capacity=bus.capacity,
            )
        )

    # Soonest first; buses with no estimate sink to the bottom rather
    # than sorting as "zero minutes away".
    arrivals.sort(
        key=lambda a: (
            a.eta.eta_seconds is None,
            a.eta.eta_seconds or 0,
        )
    )

    if arrivals:
        message = (
            f"{len(arrivals)} bus"
            f"{'es' if len(arrivals) != 1 else ''} for {stop.name}."
        )
    else:
        message = (
            f"Nothing approaching {stop.name} right now. Buses appear "
            "here once they report a live position."
        )

    return StopBoardResponse(
        stop_id=stop.id,
        stop_name=stop.name,
        generated_at=datetime.utcnow(),
        arrivals=arrivals,
        message=message,
    )