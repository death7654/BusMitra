from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ModelInfoResponse, ObservationSummary
from ..services.observations import observation_summary
from ..services.prediction import get_model_metadata


router = APIRouter(prefix="/api", tags=["Model"])


@router.get("/model/info", response_model=ModelInfoResponse)
def get_model_info(db: Session = Depends(get_db)):
    """
    What the forecast half of every number in this app is built on.

    A crowd-prediction demo can always show a confident percentage.
    The question worth answering is where it came from - how much of
    the model is a synthetic prior shipped in the box, and how much it
    has learned from this deployment. That is a number, so it should
    be an endpoint rather than a bullet point.
    """

    metadata = get_model_metadata()
    observations = observation_summary(db)

    if not metadata.get("available"):
        return ModelInfoResponse(
            available=False,
            model_path=metadata.get("model_path", ""),
            observations=ObservationSummary(**observations),
            message=(
                "No trained model on disk. Run `python ml/train.py` "
                "to build one."
            ),
        )

    synthetic_rows = int(metadata.get("synthetic_rows", 0))
    real_rows = int(metadata.get("real_rows", 0))
    total = synthetic_rows + real_rows

    share = round(real_rows / total, 4) if total else 0.0

    if real_rows == 0:
        message = (
            "Trained on synthetic data only. "
            f"{observations['real_observations']} real observation"
            f"{'' if observations['real_observations'] == 1 else 's'} "
            "gathered so far and available to the next training run."
        )
    else:
        message = (
            f"Trained on {real_rows} real observation"
            f"{'' if real_rows == 1 else 's'} from this deployment "
            f"({share:.1%} of the training set) alongside "
            f"{synthetic_rows} synthetic rows."
        )

    return ModelInfoResponse(
        available=True,
        model_path=metadata.get("model_path", ""),
        features=metadata.get("features", []),
        trained_at=metadata.get("trained_at"),
        trained_on=metadata.get("trained_on", "unknown"),
        synthetic_rows=synthetic_rows,
        real_rows=real_rows,
        real_row_share=share,
        mae=metadata.get("mae"),
        rmse=metadata.get("rmse"),
        r2=metadata.get("r2"),
        observations=ObservationSummary(**observations),
        message=message,
    )