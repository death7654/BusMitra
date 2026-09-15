"""
The learning loop: turn live measurements into training data.

The shipped model is trained on a synthetic CSV. That is fine as a
prior - it encodes "rush hours are busier than midnight" - but it has
never seen this city, these routes, or the school that empties onto
stop 7 at 15:40. This service closes that gap by periodically writing
down what the live signals actually said, so `ml/train.py` has real
rows to learn from.

The interesting part is what it refuses to record. A crowd-sourced
system that logs everything it computes will happily learn from its own
guesses, and a bus with no app users aboard measures as 0% full rather
than "unknown". Recording that would teach the model that the whole
fleet runs empty - and the model would then be cited as evidence for
it. So a snapshot is only written when real evidence sits behind the
number, and snapshots taken during a demo are tagged and excluded.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Bus, BusStop, CrowdObservation, UserPing
from .bus_matching import haversine_distance
from .crowd_aggregation import aggregate_bus_crowd


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

# Seconds between sampling passes over the fleet.
SAMPLE_INTERVAL_SECONDS = 120

# Minimum evidence weight before a measurement is worth keeping.
# Roughly: one recent report, or one phone aboard out of the five that
# earn full trust. Below this the figure is mostly an artefact of
# nobody being there to measure.
MIN_EVIDENCE = 0.2

# Never record the same bus twice inside this window, however often the
# sampler runs. Keeps a long-running server from filling the table with
# near-identical rows that would then dominate training.
MIN_GAP_SECONDS = 90

# A position older than this is not where the bus is now, so it can't
# be used to attribute the observation to a stop.
POSITION_MAX_AGE_SECONDS = 300


# ---------------------------------------------------------
# Nearest stop on the bus's own route
# ---------------------------------------------------------

def nearest_stop_on_route(db: Session, bus: Bus) -> BusStop | None:
    """
    The stop this bus is currently closest to, restricted to its own
    route.

    Restricting to the route matters: two routes can share a corridor,
    and attributing an observation to a stop the bus does not serve
    would train the model on a journey that never happens.
    """

    cutoff = datetime.utcnow() - timedelta(seconds=POSITION_MAX_AGE_SECONDS)

    ping = (
        db.query(UserPing)
        .filter(
            UserPing.bus_id == bus.id,
            UserPing.timestamp >= cutoff,
        )
        .order_by(UserPing.timestamp.desc())
        .first()
    )

    if ping is None:
        return None

    stops = (
        db.query(BusStop)
        .filter(BusStop.route_id == bus.route_id)
        .all()
    )

    if not stops:
        return None

    return min(
        stops,
        key=lambda stop: haversine_distance(
            ping.latitude,
            ping.longitude,
            stop.latitude,
            stop.longitude,
        ),
    )


# ---------------------------------------------------------
# Recording
# ---------------------------------------------------------

def recorded_recently(db: Session, bus_id: int) -> bool:
    cutoff = datetime.utcnow() - timedelta(seconds=MIN_GAP_SECONDS)

    return (
        db.query(CrowdObservation.id)
        .filter(
            CrowdObservation.bus_id == bus_id,
            CrowdObservation.timestamp >= cutoff,
        )
        .first()
        is not None
    )


def record_observation(
    db: Session,
    bus: Bus,
    crowd: dict,
    simulated: bool,
) -> CrowdObservation | None:
    """
    Write one snapshot, or return None if it isn't worth keeping.

    Returns the row so callers can assert on it; commit is the
    caller's, so a sweep over the fleet is one transaction.
    """

    evidence = min(
        1.0,
        crowd.get("passenger_weight", 0.0) + crowd.get("report_weight", 0.0),
    )

    if evidence < MIN_EVIDENCE:
        return None

    if recorded_recently(db, bus.id):
        return None

    now = datetime.utcnow()
    stop = nearest_stop_on_route(db, bus)

    observation = CrowdObservation(
        bus_id=bus.id,
        stop_id=stop.id if stop is not None else None,
        hour_of_day=now.hour,
        day_of_week=now.weekday(),
        observed_fullness=crowd["overall_fullness"],
        evidence=round(evidence, 3),
        crowd_source=crowd.get("crowd_source", "none"),
        is_simulated=1 if simulated else 0,
        timestamp=now,
    )

    db.add(observation)

    return observation


def sample_fleet(db: Session, simulated: bool) -> int:
    """
    One pass over every bus. Returns how many observations were kept.
    """

    buses = db.query(Bus).order_by(Bus.id).all()

    kept = 0

    for bus in buses:
        crowd = aggregate_bus_crowd(db=db, bus_id=bus.id)

        if crowd is None:
            continue

        if record_observation(
            db=db,
            bus=bus,
            crowd=crowd,
            simulated=simulated,
        ) is not None:
            kept += 1

    if kept:
        db.commit()

    return kept


# ---------------------------------------------------------
# Cleanup and reporting
# ---------------------------------------------------------

def purge_simulated_observations(db: Session) -> int:
    """
    Drop every observation recorded during a demo.

    Called from the demo purge so the promise the banner makes -
    nothing generated survives the demo - stays true of the training
    set too, not just of what's on screen.
    """

    deleted = (
        db.query(CrowdObservation)
        .filter(CrowdObservation.is_simulated == 1)
        .delete(synchronize_session=False)
    )

    db.commit()

    return deleted or 0


def observation_summary(db: Session) -> dict:
    """
    How much real data the deployment has gathered so far.
    """

    real = (
        db.query(CrowdObservation)
        .filter(CrowdObservation.is_simulated == 0)
        .count()
    )

    simulated = (
        db.query(CrowdObservation)
        .filter(CrowdObservation.is_simulated == 1)
        .count()
    )

    oldest = (
        db.query(CrowdObservation.timestamp)
        .filter(CrowdObservation.is_simulated == 0)
        .order_by(CrowdObservation.timestamp.asc())
        .first()
    )

    newest = (
        db.query(CrowdObservation.timestamp)
        .filter(CrowdObservation.is_simulated == 0)
        .order_by(CrowdObservation.timestamp.desc())
        .first()
    )

    return {
        "real_observations": real,
        "simulated_observations": simulated,
        "first_observed_at": oldest[0] if oldest else None,
        "last_observed_at": newest[0] if newest else None,
        "sample_interval_seconds": SAMPLE_INTERVAL_SECONDS,
        "min_evidence": MIN_EVIDENCE,
    }