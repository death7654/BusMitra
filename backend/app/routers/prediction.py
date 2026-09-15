from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus
from ..schemas import BusPredictionResponse
from ..services import demo as demo_service
from ..services import learning
from ..services.crowd_aggregation import aggregate_bus_crowd
from ..services.prediction import (
    combine_fullness,
    confidence_label,
    generate_prediction,
    get_prediction_status,
    live_evidence,
    live_share,
    observed_rows_for_bus,
)


router = APIRouter(prefix="/api", tags=["Prediction"])


CONFIDENCE_TEXT = {
    "high": "backed by live signals from this bus",
    "medium": "partly live, partly forecast",
    "low": "thin live signal, mostly forecast",
    "model_only": "no live signal on this bus - forecast only",
}


@router.get(
    "/bus/{bus_id}/prediction",
    response_model=BusPredictionResponse,
)
def get_bus_prediction(
    bus_id: int,
    stop_id: int = 1,
    db: Session = Depends(get_db),
):
    """
    The headline crowd figure: live measurement blended with the model.

    The blend weight is derived from evidence rather than fixed. A bus
    with twenty phones aboard is mostly measured; a bus with none is
    entirely forecast. Reporting the weights alongside the number is
    the point - a rider deciding whether to wait for the next bus
    deserves to know whether they're looking at a measurement or a
    guess, and a single figure can't say which it is.
    """

    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail="Bus not found.",
        )

    crowd_data = aggregate_bus_crowd(
        db=db,
        bus_id=bus_id,
    )

    live_fullness = crowd_data["overall_fullness"]

    prediction_data = generate_prediction(
        bus_id=bus_id,
        stop_id=stop_id,
    )

    predicted_fullness = prediction_data["predicted_fullness"]

    # -----------------------------------------------------
    # Evidence-weighted blend
    # -----------------------------------------------------

    evidence = live_evidence(crowd_data)
    weight = live_share(evidence)

    final_fullness = combine_fullness(
        live_fullness=live_fullness,
        predicted_fullness=predicted_fullness,
        live_weight=weight,
    )

    status_data = get_prediction_status(final_fullness)

    observed_samples = observed_rows_for_bus(bus_id)
    confidence = confidence_label(evidence, observed_samples)

    if weight > 0:
        explanation = (
            f"{round(live_fullness)}% measured live "
            f"({crowd_data['active_passengers']} phone"
            f"{'' if crowd_data['active_passengers'] == 1 else 's'} aboard, "
            f"{crowd_data['reporter_count']} rider report"
            f"{'' if crowd_data['reporter_count'] == 1 else 's'}) "
            f"weighted {weight:.2f} against a "
            f"{round(predicted_fullness)}% forecast."
        )
    else:
        explanation = (
            f"Nothing live on this bus, so the {round(final_fullness)}% "
            "figure is the model forecast alone."
        )

    # Write down what we just told the user, so it can be compared
    # against what actually happened. Nothing else in the system was
    # measuring whether its own numbers were any good - the confidence
    # labels describe how much evidence went in, which is a statement
    # about inputs rather than about accuracy.
    #
    # Wrapped because a logging failure must never cost the user their
    # answer: the prediction is already computed and correct.
    try:
        learning.log_prediction(
            db,
            bus_id=bus_id,
            stop_id=stop_id,
            predicted_fullness=predicted_fullness,
            live_fullness=live_fullness,
            final_fullness=final_fullness,
            live_weight=weight,
            confidence=confidence,
            is_simulated=demo_service.simulator.running,
        )
    except Exception:
        db.rollback()

    return {
        "bus_id": bus_id,
        "stop_id": stop_id,
        "hour_of_day": prediction_data["hour_of_day"],
        "day_of_week": prediction_data["day_of_week"],
        "live_fullness": live_fullness,
        "predicted_fullness": predicted_fullness,
        "final_fullness": final_fullness,
        "status": status_data["status"],
        "message": status_data["message"],
        "live_weight": weight,
        "model_weight": round(1.0 - weight, 3),
        "live_evidence": evidence,
        "confidence": confidence,
        "observed_samples": observed_samples,
        "explanation": explanation,
    }