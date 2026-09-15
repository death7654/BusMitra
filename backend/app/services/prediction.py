"""
ML prediction service.

Two things here are deliberate and were both bugs before:

  * The model path is anchored to this package, not to whatever
    directory uvicorn happened to be launched from. `Path("ml/...")`
    resolves against the *process* working directory, so starting the
    server from the repo root instead of `backend/` turned every
    prediction into a 500 - and the forecast page into a blank chart.

  * The model is loaded once and kept. `/api/bus/{id}/forecast` calls
    predict_fullness 31 times (24 hours + 7 days); re-reading and
    re-deserialising a 100-tree forest each time cost ~1.7s of pure
    disk work per request. It is reloaded automatically if the file
    changes on disk, so retraining still takes effect without a
    restart.
"""

from datetime import datetime
from pathlib import Path
from threading import Lock

import joblib


# backend/ - this file is backend/app/services/prediction.py
BASE_DIR = Path(__file__).resolve().parent.parent.parent

MODEL_PATH = BASE_DIR / "ml" / "model.joblib"


# ---------------------------------------------------------
# Blending live evidence with the model
# ---------------------------------------------------------

# The most of the final figure the live signal is ever allowed to own.
# At full evidence this reproduces the original 60/40 split exactly.
LIVE_MAX_SHARE = 0.60

# Evidence below this is treated as no live signal at all, rather than
# as a very quiet bus. The distinction matters: "nobody is aboard" and
# "nobody is aboard *with our app*" look identical from here, and only
# one of them is a reason to report 0%.
MIN_LIVE_EVIDENCE = 0.05


# ---------------------------------------------------------
# Model loading (cached, mtime-invalidated)
# ---------------------------------------------------------

_lock = Lock()
_cache: dict | None = None


def _load_from_disk() -> dict:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"ML model not found at {MODEL_PATH}. "
            "Run: python ml/train.py"
        )

    payload = joblib.load(MODEL_PATH)

    return {
        "mtime": MODEL_PATH.stat().st_mtime,
        "model": payload["model"],
        "features": payload["features"],
        # Older model files predate the metadata block. Treat a missing
        # one as "synthetic only", which is what those models were.
        "metadata": payload.get("metadata", {}),
    }


def _get_cached() -> dict:
    global _cache

    with _lock:
        mtime = MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else None

        if _cache is None or _cache["mtime"] != mtime:
            _cache = _load_from_disk()

        return _cache


def load_prediction_model():
    entry = _get_cached()

    return entry["model"], entry["features"]


def get_model_metadata() -> dict:
    """
    What the currently loaded model was trained on.

    Surfaced through /api/model/info so the provenance of a number is
    inspectable rather than asserted in a slide.
    """

    try:
        entry = _get_cached()
    except FileNotFoundError:
        return {
            "available": False,
            "model_path": str(MODEL_PATH),
        }

    metadata = dict(entry["metadata"])
    metadata["available"] = True
    metadata["model_path"] = str(MODEL_PATH)
    metadata["features"] = list(entry["features"])

    return metadata


def observed_rows_for_bus(bus_id: int) -> int:
    """
    How many real (non-simulated) observations of *this* bus went into
    the current model. Recorded at training time, so reading it costs
    no query.
    """

    try:
        metadata = _get_cached()["metadata"]
    except FileNotFoundError:
        return 0

    by_bus = metadata.get("real_rows_by_bus") or {}

    # joblib round-trips dict keys faithfully, but the training script
    # writes them as strings so the payload stays JSON-shaped.
    return int(by_bus.get(str(bus_id), by_bus.get(bus_id, 0)))


# ---------------------------------------------------------
# Prediction
# ---------------------------------------------------------

def predict_fullness(
    bus_id: int,
    stop_id: int,
    hour_of_day: int,
    day_of_week: int,
):
    model, features = load_prediction_model()

    input_data = {
        "hour_of_day": hour_of_day,
        "day_of_week": day_of_week,
        "bus_id": bus_id,
        "stop_id": stop_id,
    }

    prediction_input = [[input_data[feature] for feature in features]]

    predicted_fullness = model.predict(prediction_input)[0]

    predicted_fullness = max(0.0, min(100.0, predicted_fullness))

    return round(float(predicted_fullness), 2)


def get_prediction_status(predicted_fullness: float):
    if predicted_fullness >= 100:
        return {
            "status": "Bus Full",
            "message": "Bus is full. Consider another bus.",
        }

    if predicted_fullness > 80:
        return {
            "status": "Leave Later",
            "message": "Bus is expected to be highly crowded.",
        }

    if predicted_fullness >= 50:
        return {
            "status": "Moderate",
            "message": "Bus has moderate expected crowding.",
        }

    return {
        "status": "Leave Now",
        "message": "Bus is expected to have lower crowding.",
    }


def generate_prediction(
    bus_id: int,
    stop_id: int,
):
    now = datetime.now()

    predicted_fullness = predict_fullness(
        bus_id=bus_id,
        stop_id=stop_id,
        hour_of_day=now.hour,
        day_of_week=now.weekday(),
    )

    status_data = get_prediction_status(predicted_fullness)

    return {
        "bus_id": bus_id,
        "stop_id": stop_id,
        "hour_of_day": now.hour,
        "day_of_week": now.weekday(),
        "predicted_fullness": predicted_fullness,
        "status": status_data["status"],
        "message": status_data["message"],
    }


# ---------------------------------------------------------
# Live / model blending
# ---------------------------------------------------------

def live_evidence(crowd_data: dict) -> float:
    """
    How much the live figure is actually worth, 0.0 to 1.0.

    aggregate_bus_crowd already scores each signal by the evidence
    behind it - phones aboard against FULL_TRUST_DEVICES, decayed
    reports against FULL_TRUST_REPORTERS. Their sum is the total
    evidence; either one alone at full strength is enough to trust the
    live number completely.
    """

    evidence = (
        crowd_data.get("passenger_weight", 0.0)
        + crowd_data.get("report_weight", 0.0)
    )

    return round(min(1.0, max(0.0, evidence)), 3)


def live_share(evidence: float) -> float:
    """
    Fraction of the final number the live signal gets to own.

    The old blend was a flat 60/40 regardless of whether anything was
    behind the live half. On a bus with no app users aboard, live
    fullness is 0.0 by construction - so a fixed 60% weight silently
    multiplied every quiet bus's estimate by 0.4 and called the result
    a prediction. Scaling the share by evidence means no evidence
    yields the model's forecast untouched, and full evidence yields
    exactly the original 60/40.
    """

    if evidence < MIN_LIVE_EVIDENCE:
        return 0.0

    return round(LIVE_MAX_SHARE * evidence, 3)


def combine_fullness(
    live_fullness: float,
    predicted_fullness: float,
    live_weight: float | None = None,
):
    """
    Blend the live figure with the model forecast.

    live_weight defaults to the historical fixed share so existing
    callers behave unchanged; the prediction endpoint passes an
    evidence-scaled value.
    """

    weight = LIVE_MAX_SHARE if live_weight is None else live_weight
    weight = min(1.0, max(0.0, weight))

    final_fullness = (
        (live_fullness * weight)
        + (predicted_fullness * (1.0 - weight))
    )

    return round(min(final_fullness, 100.0), 2)


def confidence_label(evidence: float, observed_rows: int) -> str:
    """
    A plain-language read on how much to trust the number.

    Two independent things can go wrong: there may be no live signal,
    and the model may never have seen this bus in real conditions.
    Both are folded in, and neither is allowed to be papered over by
    the other.
    """

    if evidence < MIN_LIVE_EVIDENCE:
        return "model_only"

    if evidence >= 0.8 and observed_rows > 0:
        return "high"

    if evidence >= 0.4:
        return "medium"

    return "low"