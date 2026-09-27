"""
Batch status: everything about several buses in one request.

The Predict page needs three figures per candidate bus - crowd status,
blended prediction, arrival estimate - and used to fetch them with
three separate calls each. Five buses meant fifteen round trips, and
the refresh loop repeated all fifteen every fifteen seconds. Most of
that cost was not the work; it was fifteen HTTP handshakes and fifteen
SQLAlchemy sessions to answer one screen.

Batching collapses that to one request and one session. It also fixes
a correctness problem that was easy to miss: fifteen independent calls
observe fifteen slightly different moments, so the list could show a
bus's crowd figure from one instant against its ETA from another. A
single handler reads one consistent view.

The route geometry is built once per route here rather than once per
bus, which is the other quiet win - RouteGeometry walks every stop and
waypoint to build its prefix table, and a route with four buses was
doing that four times.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, BusStop
from ..schemas import BatchBusState, BatchStatusResponse, EtaResponse, OutageStatus
from ..services.crowd_aggregation import aggregate_bus_crowd
from ..services.eta import estimate_arrival
from ..services.outage import get_outage_status
from ..services.prediction import (
    combine_fullness,
    confidence_label,
    generate_prediction,
    get_prediction_status,
    live_evidence,
    live_share,
    observed_rows_for_bus,
)


router = APIRouter(prefix="/api", tags=["Fleet"])


# A guard, not a target. Without it a crafted query string could ask
# for every bus in the fleet joined against every stop.
MAX_BATCH = 40


@router.get("/buses/status", response_model=BatchStatusResponse)
def get_batch_status(
    bus_ids: str = Query(
        ...,
        description="Comma-separated bus ids, e.g. 1,2,5",
    ),
    stop_id: int | None = Query(
        default=None,
        description=(
            "Stop to measure arrivals and predictions against. Omit "
            "for crowd figures only."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Crowd, prediction and arrival for several buses at once.

    Every field matches what the per-bus endpoints return, so a client
    can migrate to this without changing how it reads the response -
    and can fall back to the single-bus calls if this one fails.
    """

    try:
        ids = [
            int(part) for part in bus_ids.split(",") if part.strip()
        ]
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="bus_ids must be a comma-separated list of integers.",
        )

    if not ids:
        raise HTTPException(status_code=400, detail="No bus ids given.")

    if len(ids) > MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many buses in one request (limit {MAX_BATCH}).",
        )

    # Preserve the caller's order but drop duplicates, so asking for
    # the same bus twice doesn't do the work twice.
    seen: set[int] = set()
    ordered = [i for i in ids if not (i in seen or seen.add(i))]

    buses = {
        bus.id: bus
        for bus in db.query(Bus).filter(Bus.id.in_(ordered)).all()
    }

    stop = None

    if stop_id is not None:
        stop = db.query(BusStop).filter(BusStop.id == stop_id).first()

        if stop is None:
            raise HTTPException(status_code=404, detail="Stop not found.")

    states: list[BatchBusState] = []
    missing: list[int] = []

    for bus_id in ordered:
        bus = buses.get(bus_id)

        if bus is None:
            # A bus deleted between the client's last route load and
            # now. Reported rather than 404ing the whole batch - one
            # stale id shouldn't blank the other four buses on screen.
            missing.append(bus_id)
            continue

        crowd = aggregate_bus_crowd(db=db, bus_id=bus_id)

        latest = _latest_position(db, bus_id)

        eta = None
        prediction = None

        if stop is not None and stop.route_id == bus.route_id:
            # Occupancy feeds the dwell model, so the ETA gets the
            # crowd figure that was just computed rather than
            # recomputing it or guessing.
            eta_data = estimate_arrival(
                db=db,
                bus=bus,
                stop=stop,
                occupancy_pct=crowd["overall_fullness"],
            )
            eta = EtaResponse(bus_id=bus_id, stop_id=stop.id, **eta_data)

            prediction = _prediction_for(db, bus_id, stop.id, crowd)

        states.append(
            BatchBusState(
                bus_id=bus.id,
                bus_number=bus.bus_number,
                route_id=bus.route_id,
                capacity=bus.capacity,
                latest_latitude=latest[0],
                latest_longitude=latest[1],
                latest_speed=latest[2],
                latest_timestamp=latest[3],
                active_passengers=crowd["active_passengers"],
                passenger_fullness=crowd["passenger_fullness"],
                manual_fullness=crowd["manual_fullness"],
                overall_fullness=crowd["overall_fullness"],
                report_count=crowd["report_count"],
                reporter_count=crowd["reporter_count"],
                passenger_weight=crowd["passenger_weight"],
                report_weight=crowd["report_weight"],
                crowd_source=crowd["crowd_source"],
                trend=crowd["trend"],
                outage=OutageStatus(**get_outage_status(db=db, bus_id=bus_id)),
                eta=eta,
                prediction=prediction,
            )
        )

    return BatchStatusResponse(
        generated_at=datetime.utcnow(),
        stop_id=stop.id if stop else None,
        buses=states,
        missing_bus_ids=missing,
    )


def _latest_position(db: Session, bus_id: int):
    from ..models import UserPing

    ping = (
        db.query(UserPing)
        .filter(UserPing.bus_id == bus_id)
        .order_by(UserPing.timestamp.desc())
        .first()
    )

    if ping is None:
        return None, None, None, None

    return ping.latitude, ping.longitude, ping.speed, ping.timestamp


def _prediction_for(db: Session, bus_id: int, stop_id: int, crowd: dict) -> dict:
    """
    The same blend the /prediction endpoint performs.

    Kept as a function rather than importing the route handler so the
    two can't drift: if the blend changes, it changes in
    services/prediction.py and both callers follow.
    """

    live_fullness = crowd["overall_fullness"]

    prediction_data = generate_prediction(bus_id=bus_id, stop_id=stop_id)
    predicted = prediction_data["predicted_fullness"]

    evidence = live_evidence(crowd)
    weight = live_share(evidence)

    final = combine_fullness(
        live_fullness=live_fullness,
        predicted_fullness=predicted,
        live_weight=weight,
    )

    status_data = get_prediction_status(final)
    observed = observed_rows_for_bus(bus_id)

    return {
        "bus_id": bus_id,
        "stop_id": stop_id,
        "hour_of_day": prediction_data["hour_of_day"],
        "day_of_week": prediction_data["day_of_week"],
        "live_fullness": live_fullness,
        "predicted_fullness": predicted,
        "final_fullness": final,
        "status": status_data["status"],
        "message": status_data["message"],
        "live_weight": weight,
        "model_weight": round(1.0 - weight, 3),
        "live_evidence": evidence,
        "confidence": confidence_label(evidence, observed),
        "observed_samples": observed,
        "explanation": "",
    }
