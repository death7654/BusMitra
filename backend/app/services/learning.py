"""
The background learning loop.

Three things here that all share the same shape: watch what actually
happened, write it down, and let the next request be better for it.

  * **Segment speeds.** Track each bus's progress along its route and
    record how fast it covered each piece. That becomes the traffic
    model the ETA consults for the road ahead.
  * **Calibration.** Fill in what a logged prediction turned out to be
    worth, by comparing it against a later well-evidenced measurement.
  * **Reporter trust.** Delegated to services/trust.py, run on the same
    schedule because it needs the same ground truth.

All of it is best-effort. A failure here degrades the app to exactly
what it was before any of this existed - a working ETA with no learned
traffic, and confidence labels nobody has checked - which is why every
caller wraps this in a bare except and carries on. Serving requests is
the job; learning is the improvement.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Bus, CrowdObservation, PredictionLog
from . import eta as eta_service
from . import segments, trust


# ---------------------------------------------------------
# Segment speed learning
# ---------------------------------------------------------

# Each pass looks at this much recent movement. Longer than the ETA's
# own lookback, because here we want completed traversals rather than
# the current instant.
PROGRESS_WINDOW_MINUTES = 12


def learn_segment_speeds(db: Session, is_simulated: bool) -> dict:
    """
    Record how fast each bus covered each segment it crossed recently.

    Works off the same matched track the ETA builds, so it inherits the
    leg-disambiguation that makes progress measurable on routes which
    double back. A bus that didn't move, or whose track couldn't be
    matched, contributes nothing rather than contributing a zero.
    """

    buses = db.query(Bus).all()

    recorded = 0
    rejected = 0
    considered = 0

    for bus in buses:
        geometry = eta_service.build_geometry(db, bus.route_id)

        if geometry is None:
            continue

        samples = eta_service._recent_positions(db, bus.id)

        if len(samples) < 2:
            continue

        track, _alternatives = eta_service.match_track(geometry, samples)

        if not track or len(track) != len(samples):
            continue

        considered += 1

        occupancy = _current_occupancy(db, bus.id)

        for i in range(1, len(track)):
            dt = (samples[i][0] - samples[i - 1][0]).total_seconds()

            if dt <= 0:
                continue

            moved = track[i] - track[i - 1]

            if abs(moved) < segments.MIN_TRAVERSAL_METERS:
                continue

            speed = abs(moved) / dt

            # Attribute the traversal to every segment it crossed. A
            # long sample gap can span several, and charging all of
            # them the same measured speed is the best available
            # attribution - we know the average over that stretch, not
            # the profile within it.
            low, high = sorted((track[i - 1], track[i]))

            for index in _segments_between(geometry, low, high):
                ok = segments.record_traversal(
                    db,
                    route_id=bus.route_id,
                    segment_index=index,
                    speed_ms=speed,
                    occupancy_pct=occupancy,
                    when=samples[i][0],
                    is_simulated=is_simulated,
                )

                if ok:
                    recorded += 1
                else:
                    rejected += 1

    if recorded:
        db.commit()
        # The lookup caches per route/hour bucket; new rows are
        # pointless until that cache lets them through.
        segments.invalidate_cache()

    return {
        "buses_considered": considered,
        "traversals_recorded": recorded,
        "traversals_rejected": rejected,
    }


def _segments_between(geometry, low: float, high: float) -> list[int]:
    """Indices of polyline segments overlapping a stretch of route."""

    found = []

    for i in range(len(geometry.prefix) - 1):
        if geometry.prefix[i + 1] <= low:
            continue
        if geometry.prefix[i] >= high:
            break

        found.append(i)

    return found


def _current_occupancy(db: Session, bus_id: int) -> float | None:
    """
    Latest well-evidenced occupancy figure for a bus, if one exists.

    Read from the observation table rather than recomputed, because
    this runs over the whole fleet and aggregate_bus_crowd is several
    queries per bus.
    """

    row = (
        db.query(CrowdObservation)
        .filter(
            CrowdObservation.bus_id == bus_id,
            CrowdObservation.timestamp
            >= datetime.utcnow() - timedelta(minutes=PROGRESS_WINDOW_MINUTES),
        )
        .order_by(CrowdObservation.timestamp.desc())
        .first()
    )

    return row.observed_fullness if row else None


# ---------------------------------------------------------
# Calibration
# ---------------------------------------------------------

# A prediction is compared against measurements taken in this window
# after it was served.
SCORE_AFTER_MINUTES = 4
SCORE_WITHIN_MINUTES = 15

# Ground truth has to be worth something to be truth.
MIN_TRUTH_EVIDENCE = 0.45


def log_prediction(
    db: Session,
    *,
    bus_id: int,
    stop_id: int | None,
    predicted_fullness: float,
    live_fullness: float | None,
    final_fullness: float,
    live_weight: float,
    confidence: str,
    is_simulated: bool,
    commit: bool = True,
) -> None:
    """
    Record a prediction so it can be scored later.

    Called from the prediction path. Deliberately cheap - one insert,
    no reads - because it sits in the hot path of the screen people
    actually look at.
    """

    now = datetime.now()

    db.add(
        PredictionLog(
            bus_id=bus_id,
            stop_id=stop_id,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            predicted_fullness=predicted_fullness,
            live_fullness=live_fullness,
            final_fullness=final_fullness,
            live_weight=live_weight,
            confidence=confidence,
            is_simulated=1 if is_simulated else 0,
        )
    )

    if commit:
        db.commit()


def score_predictions(db: Session, limit: int = 300) -> dict:
    """
    Fill in what logged predictions turned out to be worth.

    Only rows with a well-evidenced later measurement get scored. The
    rest stay pending, and if nothing ever measures that bus they stay
    pending forever - which is honest. An unscorable prediction is not
    a correct one.
    """

    now = datetime.utcnow()

    upper = now - timedelta(minutes=SCORE_AFTER_MINUTES)
    lower = now - timedelta(days=2)

    pending = (
        db.query(PredictionLog)
        .filter(
            PredictionLog.actual_fullness.is_(None),
            PredictionLog.timestamp >= lower,
            PredictionLog.timestamp <= upper,
        )
        .order_by(PredictionLog.timestamp)
        .limit(limit)
        .all()
    )

    scored = 0

    for row in pending:
        truth = (
            db.query(CrowdObservation)
            .filter(
                CrowdObservation.bus_id == row.bus_id,
                CrowdObservation.timestamp >= row.timestamp,
                CrowdObservation.timestamp
                <= row.timestamp + timedelta(minutes=SCORE_WITHIN_MINUTES),
                CrowdObservation.evidence >= MIN_TRUTH_EVIDENCE,
            )
            .order_by(CrowdObservation.timestamp)
            .first()
        )

        if truth is None:
            continue

        row.actual_fullness = truth.observed_fullness
        row.actual_at = truth.timestamp
        row.absolute_error = round(
            abs(row.final_fullness - truth.observed_fullness), 2
        )

        scored += 1

    if scored:
        db.commit()

    return {"scored": scored, "examined": len(pending)}


# ---------------------------------------------------------
# One pass
# ---------------------------------------------------------

def run_once(db: Session, is_simulated: bool) -> dict:
    """
    One full learning pass. Called from the background task in main.py.

    Each stage is independent and failures are contained, so a problem
    building geometry for one route can't stop reporter trust being
    scored.
    """

    summary: dict = {}

    for name, fn in (
        ("segments", lambda: learn_segment_speeds(db, is_simulated)),
        ("calibration", lambda: score_predictions(db)),
        ("trust", lambda: trust.score_pending_reports(db)),
    ):
        try:
            summary[name] = fn()
        except Exception as exc:
            db.rollback()
            summary[name] = {"error": str(exc)}

    return summary
