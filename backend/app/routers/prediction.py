from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus
from ..schemas import BusPredictionResponse
from ..services.crowd_aggregation import aggregate_bus_crowd
from ..services.prediction import (
    generate_prediction,
    combine_fullness,
    get_prediction_status,
)


router = APIRouter(prefix="/api", tags=["Prediction"])


@router.get(
    "/bus/{bus_id}/prediction",
    response_model=BusPredictionResponse,
)
def get_bus_prediction(
    bus_id: int,
    stop_id: int = 1,
    db: Session = Depends(get_db),
):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail="Bus not found.",
        )

    # Get live crowd information
    crowd_data = aggregate_bus_crowd(
        db=db,
        bus_id=bus_id,
    )

    live_fullness = crowd_data["overall_fullness"]

    # Get ML prediction
    prediction_data = generate_prediction(
        bus_id=bus_id,
        stop_id=stop_id,
    )

    predicted_fullness = prediction_data["predicted_fullness"]

    # Combine live and predicted fullness
    final_fullness = combine_fullness(
        live_fullness=live_fullness,
        predicted_fullness=predicted_fullness,
    )

    # Generate final recommendation
    status_data = get_prediction_status(
        final_fullness
    )

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
    }