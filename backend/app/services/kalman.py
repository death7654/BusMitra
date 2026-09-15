"""
Constant-velocity Kalman filter over position along the route.

The previous speed estimate was a least-squares slope through the
matched track. That is a reasonable smoother, but it has three
properties that hurt here:

  * Every sample counts equally. A fix that projected 180 m off the
    polyline is treated as confidently as one that landed on it, even
    though the first is mostly noise.
  * It has no state. Each request re-fits from scratch, so a bus that
    has been travelling steadily for ten minutes is no better known
    than one that just appeared.
  * It reports no uncertainty. The ETA has to invent its confidence
    label from sample counts and off-route distance, which are proxies
    for the thing we actually want: how sure are we of this velocity.

A Kalman filter fixes all three for about sixty lines. The state is
two numbers - position along the route and velocity along it - and the
filter is one-dimensional in space because match_track has already
collapsed the geometry to a scalar. That is the whole reason this is
cheap: projecting onto the polyline first turns a 2-D tracking problem
into a 1-D one.

Measurement noise is derived per-sample from how far the fix sat from
the line, so a bad fix widens the covariance instead of dragging the
estimate. Process noise is an acceleration term: buses speed up, slow
down and stop at lights, and the filter has to be told that the
constant-velocity assumption is only approximately true or it becomes
overconfident and stops responding to real changes.

The returned variance is what lets the ETA quote a range rather than
a fabricated point estimate.
"""

import math
from datetime import datetime


# ---------------------------------------------------------
# Tuning
# ---------------------------------------------------------

# Standard deviation of the acceleration the model doesn't know about,
# in m/s^2.
#
# This is not "how hard can a bus accelerate" - that would be around
# 1.0, and using it is wrong by an order of magnitude. The process
# noise asks a different question: how much can the bus's *average
# speed over one sample interval* differ from its average speed over
# the previous one. Sample intervals here are 15-30 seconds, and a bus
# does not sustain 1 m/s^2 for half a minute - it accelerates away from
# a stop for a few seconds and then holds a speed set by traffic.
#
# Tuned against the round-trip in tests: at 0.7 the filter reported a
# velocity standard deviation of 3.9 m/s on eight clean fixes of a bus
# holding a constant 8 m/s, which is nearly 50% relative error on data
# that pins the speed to about 0.3 m/s. That made every ETA "low"
# confidence and - worse - pushed velocity_std past the settled()
# threshold, so a moving bus could be reported as stopped.
PROCESS_ACCEL_STD = 0.12

# Floor on measurement noise, in metres. Even a fix sitting exactly on
# the polyline is not accurate to the centimetre - consumer GPS is good
# to perhaps 5-10 m in open sky and much worse between buildings.
MIN_MEASUREMENT_STD = 8.0

# How much the off-route offset inflates measurement noise. A fix 100 m
# from the line is not 100 m of along-route error, but it is evidence
# that this reading is poor, so it scales rather than adds.
OFFSET_NOISE_FACTOR = 0.8

# Starting uncertainty before any measurement has been folded in.
INITIAL_POSITION_VAR = 400.0     # 20 m std
INITIAL_VELOCITY_VAR = 25.0      # 5 m/s std - i.e. "no idea yet"

# Longest gap the filter will propagate across. Past this, the
# constant-velocity assumption has stopped meaning anything and the
# filter restarts from the new measurement rather than confidently
# extrapolating a bus into the sea.
MAX_PREDICT_SECONDS = 180.0


class AlongRouteFilter:
    """
    Tracks (position, velocity) along a route's polyline.

    Position is cumulative metres from the first stop, matching
    RouteGeometry.prefix, so the output drops straight into the same
    arithmetic the ETA already does. Velocity is signed: positive means
    travelling in the direction the stops are numbered.
    """

    def __init__(self):
        # State vector [position_m, velocity_ms] and its covariance.
        self.position: float | None = None
        self.velocity: float = 0.0

        self.p_pp = INITIAL_POSITION_VAR
        self.p_pv = 0.0
        self.p_vv = INITIAL_VELOCITY_VAR

        self.updates = 0

    # -----------------------------------------------------
    # Predict
    # -----------------------------------------------------

    def predict(self, dt: float) -> None:
        """
        Advance the state by dt seconds under constant velocity.

        F = [[1, dt], [0, 1]], so position gains velocity*dt and the
        covariance grows by the process noise Q for an unknown constant
        acceleration over that interval.
        """

        if self.position is None or dt <= 0:
            return

        self.position += self.velocity * dt

        # P = F P F' + Q, written out rather than with a matrix library
        # so this file has no numpy dependency and can be read by
        # anyone who knows the equations.
        p_pp = self.p_pp + 2 * dt * self.p_pv + dt * dt * self.p_vv
        p_pv = self.p_pv + dt * self.p_vv
        p_vv = self.p_vv

        var_a = PROCESS_ACCEL_STD ** 2

        # Q for a discrete white-noise acceleration model.
        self.p_pp = p_pp + var_a * (dt ** 4) / 4.0
        self.p_pv = p_pv + var_a * (dt ** 3) / 2.0
        self.p_vv = p_vv + var_a * (dt ** 2)

    # -----------------------------------------------------
    # Update
    # -----------------------------------------------------

    def update(self, measurement: float, offset_meters: float = 0.0) -> None:
        """
        Fold in one along-route position measurement.

        offset_meters is how far the original fix sat from the
        polyline. It doesn't shift the estimate - it decides how much
        the estimate is allowed to be shifted *by* this reading.
        """

        std = MIN_MEASUREMENT_STD + OFFSET_NOISE_FACTOR * max(0.0, offset_meters)
        r = std * std

        if self.position is None:
            # First measurement: adopt it outright. There is nothing to
            # blend with, and pretending otherwise just delays the
            # filter converging.
            self.position = measurement
            self.velocity = 0.0
            self.p_pp = r
            self.p_pv = 0.0
            self.p_vv = INITIAL_VELOCITY_VAR
            self.updates = 1
            return

        innovation = measurement - self.position
        s = self.p_pp + r

        if s <= 0:
            return

        # Kalman gain for H = [1, 0].
        k_p = self.p_pp / s
        k_v = self.p_pv / s

        self.position += k_p * innovation
        self.velocity += k_v * innovation

        p_pp = self.p_pp
        p_pv = self.p_pv

        self.p_pp = (1 - k_p) * p_pp
        self.p_pv = (1 - k_p) * p_pv
        self.p_vv = self.p_vv - k_v * p_pv

        # Numerical hygiene: covariance must stay positive definite, and
        # repeated updates in floating point can nudge it negative.
        self.p_pp = max(self.p_pp, 1e-6)
        self.p_vv = max(self.p_vv, 1e-6)

        self.updates += 1

    # -----------------------------------------------------
    # Readouts
    # -----------------------------------------------------

    @property
    def position_std(self) -> float:
        return math.sqrt(max(0.0, self.p_pp))

    @property
    def velocity_std(self) -> float:
        return math.sqrt(max(0.0, self.p_vv))

    def settled(self) -> bool:
        """
        Whether the velocity estimate is worth using.

        Two updates is the minimum for any velocity at all. The
        standard-deviation ceiling is expressed in absolute terms
        because a bus at walking pace and a bus at 60 km/h need the
        same absolute certainty before we're willing to divide by the
        number - and callers must treat False as "we don't know how
        fast this is", never as "it isn't moving". Conflating those two
        is how a moving bus gets reported as stopped.
        """

        return self.updates >= 2 and self.velocity_std < 2.5


def run_filter(
    samples: list[tuple[datetime, float, float, float]],
    track: list[float],
    offsets: list[float] | None = None,
) -> AlongRouteFilter:
    """
    Run the filter forward over an already-matched track.

    samples and track come straight out of eta._recent_positions and
    eta.match_track respectively: same length, same order, oldest
    first. offsets, when supplied, is the per-sample distance from the
    polyline used to weight each measurement.
    """

    flt = AlongRouteFilter()

    if not track:
        return flt

    previous_time = None

    for i, along in enumerate(track):
        when = samples[i][0]

        if previous_time is not None:
            dt = (when - previous_time).total_seconds()

            if dt > MAX_PREDICT_SECONDS:
                # A long silence. Everything we knew about this bus's
                # velocity is stale, so start again from here rather
                # than extrapolating three minutes of assumed motion.
                flt = AlongRouteFilter()
            else:
                flt.predict(max(0.0, dt))

        offset = offsets[i] if offsets and i < len(offsets) else 0.0
        flt.update(along, offset)

        previous_time = when

    return flt
