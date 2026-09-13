import os
import random

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


random.seed(42)
np.random.seed(42)

DATA_PATH = "data/historical_fullness.csv"
MODEL_PATH = "ml/model.joblib"


def train_model():
    print("Loading historical dataset...")

    df = pd.read_csv(DATA_PATH)

    print(f"Dataset loaded: {len(df)} rows")

    # Features used by the model
    features = [
        "hour_of_day",
        "day_of_week",
        "bus_id",
        "stop_id",
    ]

    target = "historic_fullness"

    X = df[features]
    y = df[target]

    # Split data into training and testing sets
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
    )

    print(f"Training rows: {len(X_train)}")
    print(f"Testing rows: {len(X_test)}")

    # Create Random Forest model
    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42,
        max_depth=10,
    )

    print("\nTraining Random Forest model...")

    model.fit(X_train, y_train)

    print("Model training completed.")

    # Make predictions on test data
    predictions = model.predict(X_test)

    # Evaluate model
    mae = mean_absolute_error(y_test, predictions)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))
    r2 = r2_score(y_test, predictions)

    print("\nModel Evaluation")
    print("----------------")
    print(f"MAE  : {mae:.2f}")
    print(f"RMSE : {rmse:.2f}")
    print(f"R²   : {r2:.2f}")

    # Save model
    os.makedirs("ml", exist_ok=True)

    joblib.dump(
        {
            "model": model,
            "features": features,
        },
        MODEL_PATH,
    )

    print(f"\nModel saved successfully: {MODEL_PATH}")


if __name__ == "__main__":
    train_model()