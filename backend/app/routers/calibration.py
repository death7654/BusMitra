"""
Calibration: is the app's confidence justified?

Everything else in this codebase reports how much evidence sits behind
a number. Nothing reported whether the number was *right*. Those are
different questions, and only the second one can catch a model that is
reliably eight points high - a systematic bias shows up as consistently
poor accuracy at every confidence level, which no amount of
evidence-weighting will reveal.

The sampler writes a row each time a prediction is served and fills in
what was actually observed a few minutes later. This endpoint reads
those pairs back, bucketed by the confidence label the app displayed at
the time. The useful shape of the answer is: figures we called "mostly
measured" should be closer to the truth than figures we called
"forecast only". If they aren't, the labels are decoration.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PredictionLog
from ..schemas import (
    CalibrationBucket,
    CalibrationResponse,
)


router = APIRouter(prefix="/api", tags=["Calibration"])


CONFIDENCE_ORDER = ["high", "medium", "low", "model_only"]


@router.get("/calibration", response_model=CalibrationResponse)
def get_calibration(
    days: int = Query(default=14, ge=1, le=180),
    include_simulated: bool = Query(
        default=False,
        description=(
            "Include predictions made while the demo simulator was "
            "running. Off by default: the simulator's riders follow a "
            "script, so scoring against them measures the script."
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Predicted-versus-actual, grouped by the confidence we advertised.
    """

    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(PredictionLog).filter(
        PredictionLog.timestamp >= cutoff,
        PredictionLog.actual_fullness.isnot(None),
    )

    if not include_simulated:
        query = query.filter(PredictionLog.is_simulated == 0)

    rows = query.all()

    if not rows:
        return CalibrationResponse(
            days=days,
            total_scored=0,
            buckets=[],
            overall_mae=None,
            overall_bias=None,
            message=(
                "No scored predictions yet. Rows are scored a few "
                "minutes after they're served, and only when a "
                "well-evidenced measurement of the same bus exists to "
                "compare against."
            ),
        )

    buckets: list[CalibrationBucket] = []

    for label in CONFIDENCE_ORDER:
        subset = [r for r in rows if r.confidence == label]

        if not subset:
            continue

        errors = [r.absolute_error for r in subset if r.absolute_error is not None]
        # Signed, so a model that is consistently high is
        # distinguishable from one that is merely noisy. Noise averages
        # to zero here; bias doesn't.
        signed = [
            r.final_fullness - r.actual_fullness
            for r in subset
            if r.actual_fullness is not None
        ]

        buckets.append(
            CalibrationBucket(
                confidence=label,
                samples=len(subset),
                mean_absolute_error=round(sum(errors) / len(errors), 2) if errors else None,
                bias=round(sum(signed) / len(signed), 2) if signed else None,
                within_10_points=round(
                    100.0 * sum(1 for e in errors if e <= 10) / len(errors), 1
                ) if errors else None,
                within_20_points=round(
                    100.0 * sum(1 for e in errors if e <= 20) / len(errors), 1
                ) if errors else None,
            )
        )

    all_errors = [r.absolute_error for r in rows if r.absolute_error is not None]
    all_signed = [
        r.final_fullness - r.actual_fullness
        for r in rows
        if r.actual_fullness is not None
    ]

    overall_mae = round(sum(all_errors) / len(all_errors), 2) if all_errors else None
    overall_bias = round(sum(all_signed) / len(all_signed), 2) if all_signed else None

    return CalibrationResponse(
        days=days,
        total_scored=len(rows),
        buckets=buckets,
        overall_mae=overall_mae,
        overall_bias=overall_bias,
        message=_verdict(buckets, overall_mae, overall_bias),
    )


def _verdict(buckets, mae, bias) -> str:
    """
    A plain reading of the table, including when it's unflattering.

    Writing this as prose rather than leaving the numbers to speak is
    deliberate: the whole point of the endpoint is that somebody
    actually notices when the labels stop meaning anything.
    """

    if mae is None:
        return "Not enough scored predictions to say anything yet."

    parts = [f"Mean error {mae} points across {sum(b.samples for b in buckets)} scored predictions."]

    if bias is not None and abs(bias) >= 5:
        direction = "high" if bias > 0 else "low"
        parts.append(
            f"Estimates run {abs(bias)} points {direction} on average - "
            "that's a systematic bias, not noise, and it's worth "
            "retraining."
        )

    ranked = [b for b in buckets if b.mean_absolute_error is not None]

    if len(ranked) >= 2:
        best = min(ranked, key=lambda b: b.mean_absolute_error)
        worst = max(ranked, key=lambda b: b.mean_absolute_error)

        expected_order = CONFIDENCE_ORDER.index(best.confidence) < CONFIDENCE_ORDER.index(
            worst.confidence
        )

        if expected_order:
            parts.append(
                f"Confidence labels are behaving: '{best.confidence}' "
                f"predictions are more accurate than '{worst.confidence}' ones."
            )
        else:
            parts.append(
                f"Confidence labels are inverted - '{worst.confidence}' "
                f"predictions are scoring worse than '{best.confidence}' "
                "ones. The labels are not currently earning their place."
            )

    return " ".join(parts)


@router.get("/calibration/pending")
def pending_count(db: Session = Depends(get_db)):
    """How many logged predictions are still waiting for ground truth."""

    total = db.query(func.count(PredictionLog.id)).scalar() or 0
    scored = (
        db.query(func.count(PredictionLog.id))
        .filter(PredictionLog.actual_fullness.isnot(None))
        .scalar()
        or 0
    )

    return {
        "logged": total,
        "scored": scored,
        "pending": total - scored,
    }
