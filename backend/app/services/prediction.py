from datetime import datetime
from pathlib import Path

import joblib


MODEL_PATH = Path("ml/model.joblib")


def load_prediction_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "ML model not found. Run: python ml/train.py"
        )

    model_data = joblib.load(MODEL_PATH)

    return model_data["model"], model_data["features"]


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

def combine_fullness(
    live_fullness: float,
    predicted_fullness: float,
):
    final_fullness = (
        (live_fullness * 0.60)
        + (predicted_fullness * 0.40)
    )

    return round(min(final_fullness, 100.0), 2)