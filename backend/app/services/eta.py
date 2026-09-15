"""
Arrival estimation based on position along the route.

The previous estimate divided the straight-line distance between the
bus and the stop by the bus's last reported GPS speed. That is wrong in
three separate ways, and the errors compound:

  1. Buses follow roads. Straight-line distance understates the real
     journey, badly on any route that loops or follows a coastline.
  2. It ignored direction. A bus 400m away that has already passed your
     stop and is driving away got the same "2 min" as one approaching.
  3. Instantaneous GPS speed is noisy and reads zero at every red
     light, which produced either absurd ETAs or none at all.

This module instead projects positions onto the route's own polyline -
the ordered bus_stops rows, including the dense " WP" waypoints that
exist precisely to describe the road geometry - and measures progress
*along* that line over the last few minutes. That yields direction and
an effective speed that already has stops, lights and traffic baked in,
because it's derived from where the bus actually got to.
"""

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Bus, BusStop, UserPing
from . import kalman, segments


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

EARTH_RADIUS = 6_371_000.0

# How far back to look for pings when measuring progress.
LOOKBACK_MINUTES = 10

# Position samples used for the speed fit. More samples smooth out GPS
# noise; too many and the fit lags a bus that just pulled away.
MAX_SAMPLES = 8

# A bus moving slower than this along the route is treated as stopped
# rather than crawling, so we don't divide by a near-zero speed and
# report an ETA of four hours.
MIN_MOVING_SPEED_MS = 0.6

# Effective speed is clamped into a plausible range for a city bus
# before it's used as a divisor. Outside this, GPS noise is a more
# likely explanation than the vehicle.
MIN_SPEED_MS = 1.5   # ~5 km/h
MAX_SPEED_MS = 22.0  # ~80 km/h

# Dwell is no longer a flat constant - boarding time scales with how
# full the bus is. See services/segments.dwell_seconds(). This value
# survives only as the fallback for a bus with no occupancy figure at
# all, and matches what that function returns for None.
DWELL_SECONDS = 20

# Beyond this distance from the polyline the bus isn't really on the
# route any more - a detour, a depot move, or a bad fix.
MAX_OFF_ROUTE_METERS = 300.0


def haversine_meters(lat1, lon1, lat2, lon2) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )

    return 2 * EARTH_RADIUS * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------
# Route geometry
# ---------------------------------------------------------

class RouteGeometry:
    """
    A route's stops as a measurable polyline.

    Distances are cumulative metres from the first stop, so any two
    positions on the route can be compared with a subtraction.
    """

    def __init__(self, stops: list[BusStop]):
        self.stops = stops
        self.points = [(s.latitude, s.longitude) for s in stops]

        self.prefix = [0.0]
        for i in range(len(self.points) - 1):
            self.prefix.append(
                self.prefix[-1]
                + haversine_meters(
                    self.points[i][0], self.points[i][1],
                    self.points[i + 1][0], self.points[i + 1][1],
                )
            )

        self.length = self.prefix[-1]
        self.index_by_stop_id = {s.id: i for i, s in enumerate(stops)}

        # Local planar frame. Over a single city route the error from
        # treating lat/lon as a flat grid is centimetres, and it makes
        # the point-to-segment projection ordinary vector algebra.
        self.lat0 = sum(p[0] for p in self.points) / len(self.points)
        self.cos_lat0 = math.cos(math.radians(self.lat0))

    def _to_xy(self, lat, lon):
        return (
            EARTH_RADIUS * math.radians(lon) * self.cos_lat0,
            EARTH_RADIUS * math.radians(lat),
        )

    def project(self, lat: float, lon: float) -> tuple[float, float]:
        """
        Best single guess at where a coordinate sits on the route.

        Ambiguous on any route that retraces itself - use
        project_candidates with match_track when a sequence of
        positions is available, which is almost always.
        """

        candidates = self.project_candidates(lat, lon, limit=1)
        return candidates[0] if candidates else (0.0, float("inf"))

    def project_candidates(
        self,
        lat: float,
        lon: float,
        limit: int = 4,
        cluster_meters: float = 400.0,
    ) -> list[tuple[float, float]]:
        """
        Every plausible position on the route for one coordinate.

        Routes double back: route 101 in the seed data runs 11.8 km
        between two points only 1.7 km apart, so long stretches of the
        outbound and return legs sit on the same road. A coordinate
        there genuinely matches two positions several kilometres apart,
        and picking the nearest one is a coin flip that can put a bus
        on the wrong leg - which inverts its direction of travel and
        therefore its whole ETA.

        Returns (distance_along, offset) pairs, nearest first, with
        candidates on the same stretch of line collapsed so the list
        holds genuinely distinct interpretations rather than four
        adjacent segments of one.
        """

        px, py = self._to_xy(lat, lon)

        hits: list[tuple[float, float]] = []

        for i in range(len(self.points) - 1):
            ax, ay = self._to_xy(*self.points[i])
            bx, by = self._to_xy(*self.points[i + 1])

            dx, dy = bx - ax, by - ay
            seg_sq = dx * dx + dy * dy

            if seg_sq <= 0:
                continue

            # Clamped so a point past either end of a segment projects
            # onto that segment's endpoint rather than off into space.
            t = ((px - ax) * dx + (py - ay) * dy) / seg_sq
            t = max(0.0, min(1.0, t))

            cx, cy = ax + t * dx, ay + t * dy
            offset = math.hypot(px - cx, py - cy)

            seg_length = self.prefix[i + 1] - self.prefix[i]
            hits.append((self.prefix[i] + t * seg_length, offset))

        hits.sort(key=lambda h: h[1])

        chosen: list[tuple[float, float]] = []

        for along, offset in hits:
            if any(abs(along - c[0]) < cluster_meters for c in chosen):
                continue

            chosen.append((along, offset))

            if len(chosen) >= limit:
                break

        return chosen

    def tangent_bearing(self, along: float) -> float | None:
        """
        The compass bearing the route is heading at a given position.

        Comparing this to the bus's observed direction of movement is
        what separates the two legs of an out-and-back route: they run
        the same tarmac, but facing opposite ways.
        """

        for i in range(len(self.points) - 1):
            if self.prefix[i + 1] >= along:
                ax, ay = self._to_xy(*self.points[i])
                bx, by = self._to_xy(*self.points[i + 1])

                if (bx - ax) == 0 and (by - ay) == 0:
                    return None

                return math.degrees(math.atan2(bx - ax, by - ay)) % 360

        return None

    def distance_of_stop(self, stop_id: int) -> float | None:
        index = self.index_by_stop_id.get(stop_id)
        return None if index is None else self.prefix[index]

    def named_stops_between(self, d_from: float, d_to: float) -> int:
        """
        Count real passenger stops strictly between two positions.

        Waypoints are excluded: they describe road shape, nobody boards
        at one, so they mustn't contribute dwell time.
        """

        low, high = min(d_from, d_to), max(d_from, d_to)

        return sum(
            1
            for i, stop in enumerate(self.stops)
            if low < self.prefix[i] < high and " WP" not in stop.name
        )


def build_geometry(db: Session, route_id: int) -> RouteGeometry | None:
    stops = (
        db.query(BusStop)
        .filter(BusStop.route_id == route_id)
        .order_by(BusStop.id)
        .all()
    )

    if len(stops) < 2:
        return None

    geometry = RouteGeometry(stops)

    return geometry if geometry.length > 0 else None


# ---------------------------------------------------------
# Track matching
# ---------------------------------------------------------

# How much slack to allow beyond the fastest plausible travel before
# calling a jump between candidates impossible.
JUMP_MARGIN_METERS = 80.0

# Two interpretations this far apart on the route are different legs,
# not rounding. If their costs are also within the margin below, the
# track genuinely doesn't say which one the bus is on.
AMBIGUOUS_SEPARATION_METERS = 500.0
AMBIGUOUS_COST_MARGIN = 25.0

# Cost, in metre-equivalents, of a candidate facing exactly opposite to
# the way the bus is observed to be moving. Large enough to dominate a
# tie between two legs, small enough not to override a clear position.
BEARING_WEIGHT = 400.0

# Below this, consecutive fixes are GPS jitter rather than travel and
# the bearing between them means nothing.
MIN_BEARING_MOVE_METERS = 8.0


def _bearing(lat1, lon1, lat2, lon2) -> float:
    """Compass bearing from one coordinate to another, in degrees."""

    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - (
        math.sin(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.cos(d_lon)
    )

    return math.degrees(math.atan2(y, x)) % 360


def match_track(
    geometry: "RouteGeometry",
    samples: list[tuple[datetime, float, float, float]],
) -> list[float]:
    """
    Resolve a sequence of coordinates to positions along the route.

    Each coordinate on its own may be ambiguous, but a *sequence* is
    far less so: a bus cannot be at 2 km at one moment and 9 km four
    seconds later, so the overlapping-leg ambiguity collapses as soon
    as two readings are considered together.

    This is a small Viterbi pass - emission cost is how far the fix
    lies from the line, transition cost punishes travel faster than a
    bus can manage - returning the cheapest consistent interpretation
    of the whole track, plus every rival final position that explains
    the track about as well - these are resolved later by direction,
    since a leg that puts the target stop behind the bus can simply be
    ruled out.
    """

    if not samples:
        return [], []

    candidate_sets = [
        geometry.project_candidates(lat, lon) for _, lat, lon, _ in samples
    ]

    # Degenerate route or coordinates nowhere near it.
    if not candidate_sets[0]:
        return [], []

    # cost, along, back-pointer index
    paths: list[tuple[float, float, list[float]]] = [
        (offset, along, [along]) for along, offset in candidate_sets[0]
    ]

    for i in range(1, len(samples)):
        elapsed = max(
            1.0, (samples[i][0] - samples[i - 1][0]).total_seconds()
        )
        reachable = MAX_SPEED_MS * elapsed + JUMP_MARGIN_METERS

        next_paths = []

        moved = haversine_meters(
            samples[i - 1][1], samples[i - 1][2],
            samples[i][1], samples[i][2],
        )

        observed = (
            _bearing(
                samples[i - 1][1], samples[i - 1][2],
                samples[i][1], samples[i][2],
            )
            if moved >= MIN_BEARING_MOVE_METERS
            else None
        )

        for along, offset in candidate_sets[i] or [(paths[0][1], 0.0)]:
            # A candidate whose road runs against the observed heading
            # is the wrong leg, however well its position fits.
            heading_cost = 0.0

            if observed is not None:
                tangent = geometry.tangent_bearing(along)

                if tangent is not None:
                    delta = math.radians(abs(observed - tangent) % 360)
                    heading_cost = BEARING_WEIGHT * (1 - math.cos(delta)) / 2

            best = None

            for cost, prev_along, trail in paths:
                jump = abs(along - prev_along)
                # Only the *excess* is penalised, so ordinary movement
                # costs nothing and only teleporting is rejected.
                penalty = max(0.0, jump - reachable) * 10.0
                total = cost + offset + penalty + heading_cost

                if best is None or total < best[0]:
                    best = (total, along, trail + [along])

            if best is not None:
                next_paths.append(best)

        if next_paths:
            paths = next_paths

    paths.sort(key=lambda p: p[0])

    best = paths[0]

    # Where a route runs the same road twice, two chains can explain the
    # track equally well while placing the bus on opposite legs - same
    # physical spot, opposite direction of travel, opposite answer to
    # "is my stop ahead". A long lookback usually breaks the tie by
    # catching the bus on unambiguous geometry, but when it doesn't we
    # say so instead of picking one and sounding certain.
    alternatives = [best[1]]

    for cost, along, _trail in paths[1:]:
        if any(
            abs(along - seen) < AMBIGUOUS_SEPARATION_METERS
            for seen in alternatives
        ):
            continue
        if cost - best[0] < AMBIGUOUS_COST_MARGIN:
            alternatives.append(along)

    return best[2], alternatives


# ---------------------------------------------------------
# Progress samples
# ---------------------------------------------------------

def _recent_positions(db: Session, bus_id: int):
    """
    Recent bus positions, one per instant.

    Pings are grouped by timestamp before use. Every rider on a bus
    pings from the same place at roughly the same moment, so without
    grouping a busy vehicle would fill the whole sample window with
    readings from a single instant - giving a zero time span and no
    measurable speed. This is exactly what demo mode produces, and it's
    what a full real bus produces too.
    """

    cutoff = datetime.utcnow() - timedelta(minutes=LOOKBACK_MINUTES)

    pings = (
        db.query(UserPing)
        .filter(
            UserPing.bus_id == bus_id,
            UserPing.timestamp >= cutoff,
        )
        .order_by(UserPing.timestamp.desc())
        .limit(400)
        .all()
    )

    buckets: dict[datetime, list[UserPing]] = {}

    for ping in pings:
        # Round to the second: riders on one vehicle report within
        # milliseconds of each other, not at identical microseconds.
        key = ping.timestamp.replace(microsecond=0)
        buckets.setdefault(key, []).append(ping)

    samples = []

    for when in sorted(buckets)[-MAX_SAMPLES:]:
        group = buckets[when]
        samples.append(
            (
                when,
                sum(p.latitude for p in group) / len(group),
                sum(p.longitude for p in group) / len(group),
                sum(p.speed for p in group) / len(group),
            )
        )

    return samples


def _fit_speed(times: list[float], distances: list[float]) -> float:
    """
    Least-squares slope of distance-along-route against time, in m/s.

    Signed: positive means travelling in the direction the stops are
    numbered, negative means the return leg. A single noisy fix can't
    flip the sign the way a first-to-last difference would.

    Superseded as the live estimator by the Kalman filter in
    services/kalman.py, which weights each fix by its quality and
    reports its own uncertainty. Kept because it is the obvious
    baseline to check the filter against: if the filter ever does
    worse than this on real tracks, that is a bug worth catching.
    """

    n = len(times)
    mean_t = sum(times) / n
    mean_d = sum(distances) / n

    numerator = sum(
        (times[i] - mean_t) * (distances[i] - mean_d) for i in range(n)
    )
    denominator = sum((times[i] - mean_t) ** 2 for i in range(n))

    if denominator <= 0:
        return 0.0

    return numerator / denominator


# ---------------------------------------------------------
# Arrival estimate
# ---------------------------------------------------------

def _leg_arrival(
    geometry: "RouteGeometry",
    d_bus: float,
    velocity: float,
    d_stop: float,
    learned: dict[int, float] | None = None,
    occupancy_pct: float | None = None,
) -> dict | None:
    """
    Time to the stop assuming the bus sits at d_bus on the route.

    Returns None when this interpretation has the bus already past the
    stop, which is how an impossible leg gets eliminated.

    Travel time now walks the polyline rather than dividing total
    distance by one speed: each segment is costed at whatever buses
    historically manage there at this hour, falling back to the bus's
    own measured speed on roads with no history. Dwell scales with
    occupancy, because a full bus loads slowly.
    """

    if (velocity > 0) != (d_stop > d_bus):
        return None

    remaining = abs(d_stop - d_bus)

    # Clamped before dividing: a GPS jump can otherwise fit a speed
    # that makes the arrival either instant or never.
    effective = max(MIN_SPEED_MS, min(MAX_SPEED_MS, abs(velocity)))

    stops_away = geometry.named_stops_between(d_bus, d_stop)

    travel, learned_fraction = segments.travel_seconds(
        geometry,
        d_bus,
        d_stop,
        learned or {},
        effective,
    )

    dwell = segments.dwell_seconds(occupancy_pct)

    return {
        "remaining": remaining,
        "stops_away": stops_away,
        "eta_seconds": travel + stops_away * dwell,
        "learned_fraction": learned_fraction,
        "dwell_seconds": round(dwell, 1),
    }


def _result(status: str, message: str, **extra) -> dict:
    base = {
        "status": status,
        "message": message,
        "eta_seconds": None,
        "eta_minutes": None,
        "distance_meters": None,
        "straight_line_meters": None,
        "speed_kmh": None,
        "stops_away": None,
        "off_route_meters": None,
        "eta_min_seconds": None,
        "eta_max_seconds": None,
        "sample_count": 0,
        "confidence": "none",
        # How the number was arrived at, so the client can say what it
        # is rather than just how big it is.
        "velocity_std_ms": None,
        "learned_traffic_share": 0.0,
        "dwell_seconds": None,
    }
    base.update(extra)
    return base


def estimate_arrival(
    db: Session,
    bus: Bus,
    stop: BusStop,
    occupancy_pct: float | None = None,
) -> dict:
    """
    Estimate when a bus will reach a stop.

    Returns a status rather than forcing a number: "the bus is heading
    away from you" and "we don't know" are useful answers, and inventing
    a minute figure for either is worse than admitting it.

    occupancy_pct, where the caller already has it, feeds the dwell
    model. Callers that don't pass it get the neutral fallback rather
    than an assumption of an empty bus.
    """

    if stop.route_id != bus.route_id:
        return _result(
            "off_route",
            "That stop isn't on this bus's route.",
        )

    geometry = build_geometry(db, bus.route_id)

    if geometry is None:
        return _result(
            "no_data",
            "This route has no usable geometry yet.",
        )

    d_stop = geometry.distance_of_stop(stop.id)

    if d_stop is None:
        return _result(
            "off_route",
            "That stop isn't on this bus's route.",
        )

    samples = _recent_positions(db, bus.id)

    if not samples:
        return _result(
            "no_data",
            "No live position for this bus yet.",
        )

    # Resolve the whole track at once. Doing this per-sample would let
    # consecutive fixes land on different legs of a route that doubles
    # back, and the speed fit would then read the switch as motion.
    track, alternatives = match_track(geometry, samples)

    if not track:
        return _result(
            "no_data",
            "This bus's position doesn't match its route.",
        )

    _, last_lat, last_lon, _ = samples[-1]
    _, off_route = geometry.project_candidates(last_lat, last_lon, limit=1)[0]

    # Per-sample distance from the polyline, so the filter can weight a
    # clean fix more heavily than one that landed in a side street.
    offsets = [
        geometry.project_candidates(lat, lon, limit=1)[0][1]
        for _, lat, lon, _ in samples
    ]

    # The Kalman filter replaces the least-squares slope that used to
    # live here. Same inputs, but it weights each fix by its quality,
    # carries state forward instead of re-fitting from scratch, and -
    # the part that actually changes the output - reports how sure it
    # is, which is what lets the range below be derived rather than
    # guessed. See services/kalman.py.
    state = kalman.run_filter(samples, track, offsets)

    d_bus = state.position if state.position is not None else track[-1]

    straight_line = haversine_meters(
        last_lat, last_lon, stop.latitude, stop.longitude
    )

    common = {
        "straight_line_meters": round(straight_line, 1),
        "off_route_meters": round(off_route, 1),
        "sample_count": len(samples),
    }

    if off_route > MAX_OFF_ROUTE_METERS:
        return _result(
            "off_route",
            f"This bus is {round(off_route)} m off its route - it may be "
            "on a detour.",
            **common,
        )

    if len(samples) < 2:
        return _result(
            "no_data",
            "Only one position report so far - not enough to tell which "
            "way this bus is going.",
            **common,
        )

    # Speed and direction along the route, from the filter.
    #
    # "We don't know how fast this is" and "this isn't moving" are
    # different answers, and the old code collapsed them: an unsettled
    # filter yielded velocity 0.0, which fell straight through to
    # "stopped". A bus crawling through traffic with noisy fixes would
    # be reported as parked, which is worse than reporting nothing -
    # a rider would give up and walk.
    if not state.settled():
        return _result(
            "uncertain",
            "This bus is moving, but its position reports are too "
            "scattered to say how fast yet.",
            distance_meters=round(abs(d_stop - d_bus), 1),
            velocity_std_ms=round(state.velocity_std, 2),
            confidence="low",
            **common,
        )

    velocity = state.velocity

    if abs(velocity) < MIN_MOVING_SPEED_MS:
        return _result(
            "stopped",
            "This bus isn't moving right now.",
            distance_meters=round(abs(d_stop - d_bus), 1),
            speed_kmh=round(abs(velocity) * 3.6, 1),
            velocity_std_ms=round(state.velocity_std, 2),
            **common,
        )

    speed_kmh = round(abs(velocity) * 3.6, 1)

    # Learned traffic for the road ahead, at this hour on this kind of
    # day. Empty on a route with no history, in which case the legs
    # below fall back to the bus's own speed exactly as before.
    learned = segments.segment_speeds(db, bus.route_id, datetime.now())

    # Evaluate every leg the track could plausibly be on. Most get
    # ruled out immediately: if a leg puts the stop behind the bus,
    # that interpretation would have the bus driving away, and when
    # only one leg survives the ambiguity has resolved itself.
    approaches = [
        _leg_arrival(
            geometry,
            candidate,
            velocity,
            d_stop,
            learned=learned,
            occupancy_pct=occupancy_pct,
        )
        for candidate in (alternatives or [d_bus])
    ]

    viable = [a for a in approaches if a is not None]

    if not viable:
        return _result(
            "heading_away",
            "This bus has already passed your stop and is heading the "
            "other way.",
            distance_meters=round(abs(d_stop - d_bus), 1),
            speed_kmh=speed_kmh,
            **common,
        )

    viable.sort(key=lambda a: a["eta_seconds"])

    soonest, latest = viable[0], viable[-1]

    # Two surviving legs that disagree materially mean the route runs
    # the same road twice and the track can't say which pass this is.
    # A single averaged number would be wrong in both worlds, so the
    # range is reported instead.
    spread = latest["eta_seconds"] - soonest["eta_seconds"]

    if len(viable) > 1 and spread > max(120, soonest["eta_seconds"] * 0.25):
        return _result(
            "uncertain",
            f"Between {round(soonest['eta_seconds'] / 60)} and "
            f"{round(latest['eta_seconds'] / 60)} min - this route "
            "covers the same road twice and the bus's position fits "
            "both passes.",
            eta_seconds=round(soonest["eta_seconds"]),
            eta_minutes=round(soonest["eta_seconds"] / 60, 1),
            eta_min_seconds=round(soonest["eta_seconds"]),
            eta_max_seconds=round(latest["eta_seconds"]),
            distance_meters=round(soonest["remaining"], 1),
            speed_kmh=speed_kmh,
            stops_away=soonest["stops_away"],
            confidence="low",
            velocity_std_ms=round(state.velocity_std, 2),
            learned_traffic_share=soonest["learned_fraction"],
            dwell_seconds=soonest["dwell_seconds"],
            **common,
        )

    chosen = soonest
    eta_seconds = chosen["eta_seconds"]

    # The filter knows how uncertain its velocity is, so the spread of
    # plausible arrival times can be computed rather than asserted.
    # Propagating one standard deviation of velocity through t = d/v
    # gives the band below; a bus whose speed is well established
    # produces a tight range, and one that has just appeared produces
    # an honestly wide one.
    eta_low, eta_high = _uncertainty_band(
        eta_seconds, abs(velocity), state.velocity_std
    )

    # Confidence now reflects what the filter actually knows, with the
    # old proxies kept as a floor: plenty of samples sitting close to
    # the road is still a good sign, it just isn't the whole story.
    relative_std = state.velocity_std / max(0.5, abs(velocity))

    if relative_std < 0.20 and off_route < 60 and len(samples) >= 4:
        confidence = "high"
    elif relative_std < 0.45 and len(samples) >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    minutes = eta_seconds / 60

    if eta_seconds < 45:
        message = "Arriving now."
    elif minutes < 60:
        message = f"About {round(minutes)} min away."
    else:
        message = f"Over an hour away ({round(minutes)} min)."

    if chosen["learned_fraction"] > 0.25:
        message += (
            f" {round(chosen['learned_fraction'] * 100)}% of the road "
            "ahead is timed from past runs at this hour."
        )

    return _result(
        "approaching",
        message,
        eta_seconds=round(eta_seconds),
        eta_minutes=round(minutes, 1),
        # The band, not a second point estimate. eta_seconds stays the
        # single best guess so existing callers - sorting, countdowns -
        # keep working unchanged.
        eta_min_seconds=round(eta_low),
        eta_max_seconds=round(eta_high),
        distance_meters=round(chosen["remaining"], 1),
        speed_kmh=speed_kmh,
        stops_away=chosen["stops_away"],
        confidence=confidence,
        velocity_std_ms=round(state.velocity_std, 2),
        learned_traffic_share=chosen["learned_fraction"],
        dwell_seconds=chosen["dwell_seconds"],
        **common,
    )


# Widest the band is allowed to get before it stops being useful. A
# range of "4 to 40 minutes" answers nothing; past this the estimate
# should be reported as uncertain instead.
MAX_BAND_RATIO = 2.5


def _uncertainty_band(
    eta_seconds: float,
    speed_ms: float,
    velocity_std: float,
) -> tuple[float, float]:
    """
    Plausible range of arrival times given the filter's velocity error.

    Travel time is inversely proportional to speed, so the band is
    asymmetric: being slower than expected costs more time than being
    faster saves. Computing it from the covariance rather than applying
    a flat percentage is the whole point - the width is evidence about
    this particular bus at this particular moment.
    """

    if speed_ms <= 0 or velocity_std <= 0:
        return eta_seconds, eta_seconds

    fast = speed_ms + velocity_std
    slow = max(0.4, speed_ms - velocity_std)

    low = eta_seconds * (speed_ms / fast)
    high = eta_seconds * (speed_ms / slow)

    return low, min(high, eta_seconds * MAX_BAND_RATIO)


def estimate_arrival_by_ids(
    db: Session,
    bus_id: int,
    stop_id: int,
) -> dict | None:
    bus = db.query(Bus).filter(Bus.id == bus_id).first()
    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()

    if bus is None or stop is None:
        return None

    return estimate_arrival(db, bus, stop)