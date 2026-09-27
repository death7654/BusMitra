"""
Journey planning, including transfers.

The Predict page's search is a direct-route lookup done client-side:
it scans each route's stop list for both names in order. That is fine
as far as it goes, and it goes exactly as far as one bus. Anyone whose
trip needs a change of bus got "No direct bus was found between these
locations", which is true and unhelpful.

This endpoint answers the question the rider actually asked - how do I
get from here to there - and ranks the answers by when they would
actually arrive, not just by how few buses they involve. A two-leg
journey whose first bus is pulling in now can genuinely beat a direct
bus that is twenty minutes away, and only live arrival data can tell
you that.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, BusStop
from ..schemas import (
    JourneyLegOut,
    JourneyOption,
    JourneyPlanResponse,
)
from ..services import journeys as journey_service
from ..services.crowd_aggregation import aggregate_bus_crowd
from ..services.eta import estimate_arrival


router = APIRouter(prefix="/api", tags=["Journeys"])


# More than this and the list stops being a decision aid.
MAX_OPTIONS = 6


@router.get("/journey", response_model=JourneyPlanResponse)
def plan_journey(
    from_stop: str = Query(..., description="Starting stop name"),
    to_stop: str = Query(..., description="Destination stop name"),
    db: Session = Depends(get_db),
):
    """
    Ways to travel between two stops, soonest realistic arrival first.

    Each leg reports the buses that serve it and, where one is
    approaching the boarding stop, how full it is and when it gets
    there. Legs after the first deliberately carry no ETA: the
    connecting bus you'll catch is not the one approaching that stop
    now, and showing its current arrival time would be a confident
    answer to a question nobody asked.
    """

    if from_stop == to_stop:
        raise HTTPException(
            status_code=400,
            detail="Start and destination are the same stop.",
        )

    options = journey_service.plan(db, from_stop, to_stop)

    if not options:
        return JourneyPlanResponse(
            from_stop=from_stop,
            to_stop=to_stop,
            generated_at=datetime.utcnow(),
            options=[],
            message=(
                f"No route or combination of routes connects {from_stop} "
                f"to {to_stop} in this direction. Try reversing them."
            ),
        )

    rendered: list[JourneyOption] = []

    for journey in options[: MAX_OPTIONS * 2]:
        legs: list[JourneyLegOut] = []
        first_eta_seconds: int | None = None

        for index, leg in enumerate(journey.legs):
            best = None

            if index == 0:
                best = _best_boarding(db, leg)

                if best is not None:
                    first_eta_seconds = best["eta_seconds"]

            legs.append(
                JourneyLegOut(
                    route_id=leg.route_id,
                    route_number=leg.route_number,
                    route_name=leg.route_name,
                    board_stop_id=leg.board_stop_id,
                    board_stop_name=leg.board_stop_name,
                    alight_stop_id=leg.alight_stop_id,
                    alight_stop_name=leg.alight_stop_name,
                    stops_count=leg.stops_count,
                    bus_ids=leg.bus_ids,
                    best_bus_id=best["bus_id"] if best else None,
                    best_bus_number=best["bus_number"] if best else None,
                    eta_seconds=best["eta_seconds"] if best else None,
                    eta_status=best["status"] if best else "no_data",
                    overall_fullness=best["fullness"] if best else None,
                )
            )

        rendered.append(
            JourneyOption(
                legs=legs,
                transfers=journey.transfers,
                total_stops=journey.total_stops,
                first_departure_seconds=first_eta_seconds,
                score=_score(journey, first_eta_seconds),
            )
        )

    # Rank by the score rather than by transfer count alone: a journey
    # you can start now is often better than one you can start in
    # twenty minutes, even with a change in the middle.
    rendered.sort(key=lambda o: o.score)

    return JourneyPlanResponse(
        from_stop=from_stop,
        to_stop=to_stop,
        generated_at=datetime.utcnow(),
        options=rendered[:MAX_OPTIONS],
        message=(
            f"{len(rendered[:MAX_OPTIONS])} way"
            f"{'s' if len(rendered[:MAX_OPTIONS]) != 1 else ''} to get "
            f"from {from_stop} to {to_stop}."
        ),
    )


def _best_boarding(db: Session, leg) -> dict | None:
    """
    The soonest bus on this leg that is actually coming to the boarding
    stop. Returns None when none of them has a usable estimate.
    """

    stop = (
        db.query(BusStop)
        .filter(BusStop.id == leg.board_stop_id)
        .first()
    )

    if stop is None:
        return None

    best = None

    for bus_id in leg.bus_ids:
        bus = db.query(Bus).filter(Bus.id == bus_id).first()

        if bus is None:
            continue

        crowd = aggregate_bus_crowd(db=db, bus_id=bus_id)

        eta = estimate_arrival(
            db=db,
            bus=bus,
            stop=stop,
            occupancy_pct=crowd["overall_fullness"],
        )

        if eta["status"] not in ("approaching", "uncertain"):
            continue

        if eta["eta_seconds"] is None:
            continue

        if best is None or eta["eta_seconds"] < best["eta_seconds"]:
            best = {
                "bus_id": bus_id,
                "bus_number": bus.bus_number,
                "eta_seconds": eta["eta_seconds"],
                "status": eta["status"],
                "fullness": crowd["overall_fullness"],
            }

    return best


# Rough seconds spent per intermediate stop, used only for ranking.
# The real per-stop cost is the ETA's business; here we just need the
# options to sort sensibly against each other.
SECONDS_PER_STOP = 75


def _score(journey, first_eta_seconds: int | None) -> float:
    """
    Lower is better. Combines waiting, riding and the cost of changing.

    A journey whose first bus has no live estimate is scored as if the
    wait were the interval between buses - pessimistic on purpose, so
    an option we can actually see beating it wins, and an option we
    simply know nothing about doesn't top the list by default.
    """

    unknown_wait = 900

    wait = first_eta_seconds if first_eta_seconds is not None else unknown_wait

    ride = journey.total_stops * SECONDS_PER_STOP
    transfer = journey.transfers * journey_service.TRANSFER_PENALTY_SECONDS

    return wait + ride + transfer