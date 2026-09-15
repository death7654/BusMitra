"""
Train the crowd-fullness model.

The model starts from a synthetic dataset - a reasonable prior about
rush hours and weekends that lets the app work on day one - and folds
in whatever the deployment has actually observed since. Over time the
real rows should come to dominate; until they do, `/api/model/info`
reports honestly that they haven't.

Two choices worth defending:

  * Simulated observations are excluded. Demo mode writes rows tagged
    is_simulated=1 so the demo can exercise the whole pipeline, but a
    model fitted to a simulator that was itself built from assumptions
    would just be laundering those assumptions into a number.
  * Real rows carry a sample weight and a multiplier. Each observation
    is already scored by how much evidence sat behind it, and a
    measurement of this city beats a row generated from a formula - so
    a few hundred real rows can shift the model without being drowned
    by five thousand synthetic ones.

Run from the backend/ directory:

    python ml/train.py
"""

import os
import random
import sqlite3
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


random.seed(42)
np.random.seed(42)

# Anchored to the file, so training works from any working directory.
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_PATH = BASE_DIR / "data" / "historical_fullness.csv"
DB_PATH = BASE_DIR / "data" / "bus.db"
MODEL_PATH = BASE_DIR / "ml" / "model.joblib"

FEATURES = [
    "hour_of_day",
    "day_of_week",
    "bus_id",
    "stop_id",
]

TARGET = "historic_fullness"

# How much more a real observation counts than a synthetic row. Real
# data is scarce early on, and without this the prior would swamp it
# for months.
REAL_ROW_MULTIPLIER = 8.0

# Below this, the real rows are noise rather than signal and are more
# likely to overfit the handful of buses that happened to be busy.
MIN_REAL_ROWS = 25


def load_synthetic() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)

    df = df[FEATURES + [TARGET]].copy()
    df["sample_weight"] = 1.0
    df["origin"] = "synthetic"

    return df


def load_observed() -> pd.DataFrame:
    """
    Real observations recorded by the running deployment.

    Read with sqlite3 directly rather than through the app's SQLAlchemy
    models: training is an offline script and shouldn't need the web
    application to import cleanly in order to run.
    """

    empty = pd.DataFrame(
        columns=FEATURES + [TARGET, "sample_weight", "origin"]
    )

    if not DB_PATH.exists():
        return empty

    connection = sqlite3.connect(DB_PATH)

    try:
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='crowd_observations'",
            connection,
        )

        if tables.empty:
            return empty

        df = pd.read_sql_query(
            """
            SELECT hour_of_day,
                   day_of_week,
                   bus_id,
                   stop_id,
                   observed_fullness,
                   evidence
            FROM crowd_observations
            WHERE is_simulated = 0
              AND stop_id IS NOT NULL
            """,
            connection,
        )

    finally:
        connection.close()

    if df.empty:
        return empty

    df = df.rename(columns={"observed_fullness": TARGET})

    # Evidence is already 0-1; the multiplier is what makes a real row
    # outweigh a synthetic one rather than merely match it.
    df["sample_weight"] = (
        df["evidence"].clip(lower=0.1) * REAL_ROW_MULTIPLIER
    )
    df["origin"] = "observed"

    return df[FEATURES + [TARGET, "sample_weight", "origin"]]


def train_model():
    print("Loading synthetic dataset...")
    synthetic = load_synthetic()
    print(f"  synthetic rows: {len(synthetic)}")

    print("Loading observed data from this deployment...")
    observed = load_observed()
    print(f"  real observations: {len(observed)}")

    if len(observed) < MIN_REAL_ROWS:
        if len(observed):
            print(
                f"  fewer than {MIN_REAL_ROWS} real rows - "
                "training on synthetic data only."
            )

        df = synthetic
        observed_used = 0
        trained_on = "synthetic"
    else:
        df = pd.concat([synthetic, observed], ignore_index=True)
        observed_used = len(observed)
        trained_on = "synthetic+observed"

    X = df[FEATURES]
    y = df[TARGET]
    weights = df["sample_weight"]

    X_train, X_test, y_train, y_test, w_train, _ = train_test_split(
        X,
        y,
        weights,
        test_size=0.2,
        random_state=42,
    )

    print(f"\nTraining rows: {len(X_train)}")
    print(f"Testing rows: {len(X_test)}")

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42,
        max_depth=10,
    )

    print("\nTraining Random Forest model...")

    model.fit(X_train, y_train, sample_weight=w_train)

    print("Model training completed.")

    predictions = model.predict(X_test)

    mae = float(mean_absolute_error(y_test, predictions))
    rmse = float(np.sqrt(mean_squared_error(y_test, predictions)))
    r2 = float(r2_score(y_test, predictions))

    print("\nModel Evaluation")
    print("----------------")
    print(f"MAE  : {mae:.2f}")
    print(f"RMSE : {rmse:.2f}")
    print(f"R2   : {r2:.2f}")

    # Per-bus real-row counts let the API say, per prediction, whether
    # the model has ever seen *this* bus in real conditions - which is
    # a different question from whether it has seen any real data.
    if observed_used:
        counts = observed["bus_id"].value_counts().to_dict()
        real_rows_by_bus = {str(int(k)): int(v) for k, v in counts.items()}
    else:
        real_rows_by_bus = {}

    metadata = {
        "trained_at": datetime.utcnow(),
        "trained_on": trained_on,
        "synthetic_rows": len(synthetic),
        "real_rows": observed_used,
        "real_rows_by_bus": real_rows_by_bus,
        "real_row_multiplier": REAL_ROW_MULTIPLIER,
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "r2": round(r2, 3),
    }

    os.makedirs(MODEL_PATH.parent, exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "metadata": metadata,
        },
        MODEL_PATH,
    )

    print(f"\nModel saved successfully: {MODEL_PATH}")
    print(f"Trained on: {trained_on}")


if __name__ == "__main__":
    train_model()