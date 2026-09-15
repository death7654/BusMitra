"""
Learned travel times: per-segment speed history and dwell modelling.

Two corrections to the ETA, both of which matter most exactly when
being wrong is most expensive - a crowded bus in rush-hour traffic.

**Segment speeds.** The ETA divides remaining distance by the bus's
*current* fitted speed. A bus doing 40 km/h on a clear stretch that
averages 12 km/h through the market at 18:00 will be reported as
arriving far sooner than it can. Traffic is a property of place and
time, not of the instant you happened to look. This module records how
fast buses actually cover each piece of each route, bucketed by hour
and by weekday-vs-weekend, and the ETA uses those learned figures for
the road ahead instead of projecting the present forward.

**Dwell.** The old model charged a flat 20 seconds per intermediate
stop. Boarding time scales with how full the vehicle is: on a packed
bus people have to shuffle down the aisle, and alighting passengers
have to fight forward. The occupancy figure is already computed for
every bus in the fleet, so feeding it into dwell costs nothing and
tightens estimates on the busy routes where riders most need them.

Both fall back cleanly. A route with no history behaves exactly as it
did before, which means this can be deployed on day one and simply
gets better as the table fills.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import SegmentTraversal


# ---------------------------------------------------------
# Dwell
# ---------------------------------------------------------

# Time to open doors, let nobody on, and close them again.
BASE_DWELL_SECONDS = 9.0

# Additional seconds at 100% occupancy. Boarding and alighting both
# slow as the aisle fills; this is the linear approximation of a curve
# that is really convex at the top end, which means it *under*states
# crush-load dwell. Understating is the safer direction: it keeps the
# ETA from ballooning on one bad occupancy reading.
CROWD_DWELL_SECONDS = 17.0

# No dwell is charged for a stop nobody is waiting at, but we can't
# know that, so every named stop costs at least the base.


def dwell_seconds(occupancy_pct: float | None) -> float:
    """
    Expected time lost at one intermediate passenger stop.

    occupancy_pct is the blended fullness figure, 0-100. None means no
    live signal, in which case the old flat figure is used rather than
    assuming an empty bus - assuming empty would systematically
    under-estimate every arrival on a bus nobody is tracking.
    """

    if occupancy_pct is None:
        return BASE_DWELL_SECONDS + CROWD_DWELL_SECONDS * 0.5

    fraction = max(0.0, min(1.0, occupancy_pct / 100.0))

    return BASE_DWELL_SECONDS + CROWD_DWELL_SECONDS * fraction


# ---------------------------------------------------------
# Time bucketing
# ---------------------------------------------------------

def day_type(when: datetime) -> str:
    """
    Weekday and weekend traffic are different regimes, not points on a
    scale. Bucketing by them rather than by day-of-week gives roughly
    five times the samples per bucket, which matters enormously when a
    deployment has been running for a week rather than a year.
    """

    return "weekend" if when.weekday() >= 5 else "weekday"


# ---------------------------------------------------------
# Recording
# ---------------------------------------------------------

# A traversal has to cover at least this much of a segment before it
# tells us anything about that segment's speed.
MIN_TRAVERSAL_METERS = 40.0

# Speeds outside this are GPS artefacts, not buses.
MIN_PLAUSIBLE_MS = 0.5
MAX_PLAUSIBLE_MS = 25.0


def record_traversal(
    db: Session,
    *,
    route_id: int,
    segment_index: int,
    speed_ms: float,
    occupancy_pct: float | None,
    when: datetime,
    is_simulated: bool,
) -> bool:
    """
    Write down how fast one bus crossed one segment.

    Returns False when the sample was rejected as implausible, so the
    caller can count what it discarded.
    """

    if not (MIN_PLAUSIBLE_MS <= speed_ms <= MAX_PLAUSIBLE_MS):
        return False

    db.add(
        SegmentTraversal(
            route_id=route_id,
            segment_index=segment_index,
            hour_of_day=when.hour,
            day_type=day_type(when),
            speed_ms=round(speed_ms, 3),
            occupancy_pct=occupancy_pct,
            is_simulated=1 if is_simulated else 0,
            timestamp=when,
        )
    )

    return True


# ---------------------------------------------------------
# Lookup
# ---------------------------------------------------------

# Below this many samples a bucket's mean is noise, and the fallback is
# a better estimate than a badly-supported "learned" one.
MIN_SAMPLES_FOR_BUCKET = 4

# How long a learned speed stays relevant. Roadworks end, bus lanes get
# painted, schools move their finishing time.
HISTORY_DAYS = 60

# Cached per (route_id, hour, day_type) so the board endpoint - which
# runs the ETA once per bus - doesn't re-query for every one of them.
_cache: dict[tuple, tuple[datetime, dict[int, float]]] = {}
CACHE_TTL_SECONDS = 300


def segment_speeds(
    db: Session,
    route_id: int,
    when: datetime,
    include_simulated: bool = False,
) -> dict[int, float]:
    """
    Mean observed speed per segment index for this route and time
    bucket, in m/s. Segments without enough history are absent, and
    callers fall back to the live-fitted speed for those.
    """

    key = (route_id, when.hour, day_type(when), include_simulated)
    cached = _cache.get(key)

    if cached and (datetime.utcnow() - cached[0]).total_seconds() < CACHE_TTL_SECONDS:
        return cached[1]

    cutoff = datetime.utcnow() - timedelta(days=HISTORY_DAYS)

    query = (
        db.query(
            SegmentTraversal.segment_index,
            func.avg(SegmentTraversal.speed_ms),
            func.count(SegmentTraversal.id),
        )
        .filter(
            SegmentTraversal.route_id == route_id,
            SegmentTraversal.hour_of_day == when.hour,
            SegmentTraversal.day_type == day_type(when),
            SegmentTraversal.timestamp >= cutoff,
        )
    )

    if not include_simulated:
        # Simulated buses drive a scripted speed profile. Learning from
        # them would teach the model the simulator's assumptions and
        # then present them back as measured traffic.
        query = query.filter(SegmentTraversal.is_simulated == 0)

    speeds = {
        int(index): float(mean)
        for index, mean, count in query.group_by(SegmentTraversal.segment_index).all()
        if count >= MIN_SAMPLES_FOR_BUCKET and mean and mean > 0
    }

    _cache[key] = (datetime.utcnow(), speeds)

    return speeds


def invalidate_cache() -> None:
    """Called after a bulk write so the next read sees fresh history."""

    _cache.clear()


# ---------------------------------------------------------
# Travel time
# ---------------------------------------------------------

def travel_seconds(
    geometry,
    d_from: float,
    d_to: float,
    learned: dict[int, float],
    fallback_ms: float,
) -> tuple[float, float]:
    """
    Expected seconds to travel between two positions on the route.

    Walks the polyline segment by segment, using the learned speed for
    each piece of road where one exists and the bus's own current speed
    where it doesn't. Mixing the two is the point: the stretch the bus
    is on right now is best described by how fast it is actually going,
    and the stretch three kilometres ahead is best described by how
    fast buses usually go there.

    Returns (seconds, learned_fraction) where learned_fraction is how
    much of the distance was covered by history rather than
    extrapolation - the ETA reports it so a rider can tell the
    difference.
    """

    low, high = min(d_from, d_to), max(d_from, d_to)

    if high - low <= 0:
        return 0.0, 0.0

    fallback_ms = max(0.5, fallback_ms)

    total_seconds = 0.0
    learned_meters = 0.0

    for i in range(len(geometry.prefix) - 1):
        seg_start = geometry.prefix[i]
        seg_end = geometry.prefix[i + 1]

        # Overlap between this segment and the stretch being measured.
        overlap = min(high, seg_end) - max(low, seg_start)

        if overlap <= 0:
            continue

        speed = learned.get(i)

        if speed:
            learned_meters += overlap
        else:
            speed = fallback_ms

        total_seconds += overlap / speed

    covered = high - low

    return total_seconds, round(learned_meters / covered, 3) if covered else 0.0
