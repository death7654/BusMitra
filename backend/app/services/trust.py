"""
Reporter trust: weighting crowd reports by past accuracy.

Every report currently counts the same. That is the right default for
a system with no history, but it has two failure modes that show up as
soon as the app has real users:

  * Someone reporting "very high" on every bus they board, whether for
    amusement or to keep a seat free, moves the average as much as a
    careful rider.
  * Honest people are calibrated differently. One rider's "high" is
    another's "moderate", and neither is lying.

Both are the same problem - a report's *information content* varies by
reporter - and both are fixed the same way: score each reporter against
what was later measured, and weight their future reports by how close
they have tended to be.

The scoring is deliberately conservative:

  * Only reports that can be checked are scored. A report on a bus with
    no phones aboard has no ground truth, so it neither helps nor hurts
    the reporter's standing.
  * Trust moves slowly, via a running mean, and is floored well above
    zero. A reporter is never silenced - a persistently-wrong one is
    damped to a third of a good reporter's weight, which is enough to
    stop them steering the number without discarding a human being's
    direct observation of a vehicle we cannot otherwise see inside.
  * New reporters start at full trust, not zero. Assuming bad faith by
    default would make the first report from every real user useless,
    which is most reports in any deployment that is actually growing.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import CrowdObservation, CrowdReport, ReporterScore


# ---------------------------------------------------------
# Tuning
# ---------------------------------------------------------

# Where everyone starts, and the ceiling.
DEFAULT_TRUST = 1.0

# Floor. A reporter who has been consistently far out still counts for
# this much - see the module docstring for why it isn't zero.
MIN_TRUST = 0.33

# Absolute percentage error at which a report earns the floor. Below
# it, trust scales linearly. 45 points is deliberately generous: the
# five-level scale buckets at 20-point intervals, so being one bucket
# out is normal disagreement and shouldn't cost anything much.
MAX_TOLERATED_ERROR = 45.0

# How many scored reports before trust is fully applied. Under this,
# the score is blended toward the default so one unlucky report can't
# mark someone down.
CONFIDENCE_REPORTS = 5

# A report is compared against measurements taken in this window after
# it. Long enough for the sampler to have written something, short
# enough that the bus hasn't emptied at a terminus in between.
GRACE_MINUTES = 3
CHECK_WINDOW_MINUTES = 12

# Ground truth has to be worth something. Below this evidence weight the
# observation isn't a measurement, it's a rumour.
MIN_TRUTH_EVIDENCE = 0.45


# ---------------------------------------------------------
# Reading
# ---------------------------------------------------------

def get_trust(db: Session, user_id: int) -> float:
    """
    This reporter's current weight multiplier, 0.33 to 1.0.

    Unknown reporters get the default. This is called once per distinct
    reporter per aggregation, which is a handful of rows.
    """

    score = (
        db.query(ReporterScore)
        .filter(ReporterScore.user_id == user_id)
        .first()
    )

    if score is None or score.scored_reports <= 0:
        return DEFAULT_TRUST

    return _blend_toward_default(score.trust, score.scored_reports)


def get_trust_map(db: Session, user_ids) -> dict[int, float]:
    """Bulk version, so aggregation costs one query rather than N."""

    user_ids = list(user_ids)

    if not user_ids:
        return {}

    rows = (
        db.query(ReporterScore)
        .filter(ReporterScore.user_id.in_(user_ids))
        .all()
    )

    found = {
        row.user_id: _blend_toward_default(row.trust, row.scored_reports)
        for row in rows
        if row.scored_reports > 0
    }

    return {uid: found.get(uid, DEFAULT_TRUST) for uid in user_ids}


def _blend_toward_default(trust: float, scored: int) -> float:
    """
    Pull a thinly-evidenced score back toward 1.0.

    With one scored report, the score is mostly the default; by
    CONFIDENCE_REPORTS it is applied in full. This is the same
    evidence-weighting idea the crowd aggregation already uses, applied
    one level up.
    """

    confidence = min(1.0, scored / CONFIDENCE_REPORTS)
    blended = DEFAULT_TRUST * (1 - confidence) + trust * confidence

    return round(max(MIN_TRUST, min(DEFAULT_TRUST, blended)), 3)


# ---------------------------------------------------------
# Scoring
# ---------------------------------------------------------

CROWD_LEVEL_TO_PERCENTAGE = {1: 20.0, 2: 40.0, 3: 60.0, 4: 80.0, 5: 100.0}


def _trust_from_error(mean_error: float) -> float:
    """Map a mean absolute percentage error onto the trust range."""

    fraction = max(0.0, min(1.0, mean_error / MAX_TOLERATED_ERROR))

    return DEFAULT_TRUST - (DEFAULT_TRUST - MIN_TRUST) * fraction


def score_pending_reports(db: Session, limit: int = 200) -> dict:
    """
    Compare recent reports against what was later measured.

    Run periodically from the background sampler. Returns a small
    summary for logging.

    A report is scorable when the observation sampler recorded a
    well-evidenced measurement of the same bus shortly afterwards. Most
    reports on a quiet deployment will never be scorable, and that is
    the correct outcome - it means those reporters keep full trust
    rather than being judged on a guess.
    """

    now = datetime.utcnow()

    # Old enough that ground truth may exist, recent enough that we
    # haven't already looked at it.
    upper = now - timedelta(minutes=GRACE_MINUTES)
    lower = now - timedelta(minutes=CHECK_WINDOW_MINUTES + GRACE_MINUTES)

    reports = (
        db.query(CrowdReport)
        .filter(
            CrowdReport.timestamp >= lower,
            CrowdReport.timestamp <= upper,
            CrowdReport.scored == 0,
        )
        .order_by(CrowdReport.timestamp)
        .limit(limit)
        .all()
    )

    scored = 0
    skipped = 0

    for report in reports:
        stated = CROWD_LEVEL_TO_PERCENTAGE.get(report.crowd_level)

        if stated is None:
            report.scored = 1
            continue

        truth = (
            db.query(CrowdObservation)
            .filter(
                CrowdObservation.bus_id == report.bus_id,
                CrowdObservation.timestamp >= report.timestamp,
                CrowdObservation.timestamp
                <= report.timestamp + timedelta(minutes=CHECK_WINDOW_MINUTES),
                CrowdObservation.evidence >= MIN_TRUTH_EVIDENCE,
                CrowdObservation.is_simulated == 0,
            )
            .order_by(CrowdObservation.timestamp)
            .first()
        )

        if truth is None:
            # Nothing to check against. Leave scored=0 only if the
            # report is still inside its window; past that, mark it
            # done so it isn't re-examined forever.
            if report.timestamp < lower + timedelta(minutes=1):
                report.scored = 1
                skipped += 1
            continue

        error = abs(stated - truth.observed_fullness)

        _apply_score(db, report.user_id, error)

        report.scored = 1
        scored += 1

    if scored or skipped:
        db.commit()

    return {"scored": scored, "unscorable": skipped}


def _apply_score(db: Session, user_id: int, error: float) -> None:
    """Fold one observed error into a reporter's running mean."""

    score = (
        db.query(ReporterScore)
        .filter(ReporterScore.user_id == user_id)
        .first()
    )

    if score is None:
        score = ReporterScore(
            user_id=user_id,
            scored_reports=0,
            mean_error=0.0,
            trust=DEFAULT_TRUST,
        )
        db.add(score)

    n = score.scored_reports
    score.mean_error = (score.mean_error * n + error) / (n + 1)
    score.scored_reports = n + 1
    score.trust = round(_trust_from_error(score.mean_error), 3)
    score.updated_at = datetime.utcnow()
