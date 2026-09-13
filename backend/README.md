````markdown
# 🚌 Bus Tracking and Crowd Prediction System - Backend

## 1. Overview

This is the Python backend for the **Bus Tracking and Crowd Prediction System**.

The backend receives:
- GPS location data
- Bus check-ins
- Manual crowd reports

It then:

1. Matches users to buses using GPS when possible.
2. Tracks active passengers.
3. Calculates current bus crowding.
4. Uses historical data with a Random Forest model to predict future crowding.
5. Combines live and predicted fullness.
6. Returns a travel recommendation to the frontend.

The backend communicates with the Tauri/frontend application through **HTTP + JSON**.

---

## 2. Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend language |
| FastAPI | REST API |
| Uvicorn | Server |
| SQLite | Database |
| SQLAlchemy | Database ORM |
| Pydantic | Request/response validation |
| pandas | ML dataset handling |
| NumPy | Numerical operations |
| scikit-learn | Machine Learning |
| RandomForestRegressor | Fullness prediction |
| joblib | ML model storage |
| pytest + HTTPX | API testing |

---

## 3. Backend Structure

```text
backend/
│
├── app/
│   ├── main.py                  # FastAPI application
│   ├── database.py              # SQLite + SQLAlchemy setup
│   ├── models.py                # Database models
│   ├── schemas.py               # Pydantic schemas
│   ├── seed.py                  # Demo database data
│   │
│   ├── routers/
│   │   ├── tracking.py          # GPS tracking API
│   │   ├── crowd.py             # Check-in/crowd APIs
│   │   ├── bus.py               # Bus status API
│   │   └── prediction.py        # ML prediction API
│   │
│   └── services/
│       ├── bus_matching.py      # GPS → bus matching
│       ├── tracking.py          # Tracking logic
│       ├── crowd.py             # Crowd/check-in logic
│       ├── crowd_aggregation.py # Crowd calculations
│       ├── prediction.py        # ML prediction logic
│       └── notifications.py     # Crowd status decisions
│
├── ml/
│   ├── train.py                 # Model training
│   └── model.joblib             # Trained Random Forest
│
├── data/
│   ├── bus.db                   # SQLite database
│   └── historical_fullness.csv  # Synthetic ML dataset
│
├── tests/
│   ├── __init__.py
│   └── test_api.py              # Automated API tests
│
├── requirements.txt
└── README.md
````

---

# 4. Database Models

The SQLite database contains the following main tables.

### Route

```text
id
route_number
route_name
```

### Bus

```text
id
bus_number
route_id
capacity
```

### BusStop

```text
id
name
latitude
longitude
route_id
```

### UserPing

Stores GPS information:

```text
id
user_id
latitude
longitude
speed
bus_id
timestamp
```

### CheckIn

Stores manual bus check-ins:

```text
id
user_id
bus_id
timestamp
```

### CrowdReport

Stores user-submitted crowd levels:

```text
id
user_id
bus_id
crowd_level
timestamp
```

---

# 5. Running the Backend

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Seed the Database

```bash
python -m app.seed
```

## Start FastAPI

```bash
uvicorn app.main:app --reload
```

Backend:

```text
http://127.0.0.1:8000
```

Swagger API documentation:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
GET /health
```

Expected response:

```json
{
  "status": "ok"
}
```

---

# 6. API Endpoints

## GPS Tracking

```http
POST /api/ping
```

### Request

```json
{
  "user_id": 1,
  "latitude": 11.2588,
  "longitude": 75.7804,
  "speed": 25.5
}
```

The backend:

* checks the user's speed
* ignores speeds below 5 km/h
* searches for a nearby bus/route
* attempts GPS-based bus matching
* stores the valid ping
* returns matching information

GPS matching uses a lightweight geographic-distance calculation with a **30-meter matching threshold**.

---

## Manual Check-in

```http
POST /api/checkin
```

### Request

```json
{
  "user_id": 1,
  "bus_id": 1
}
```

Used as a fallback when GPS matching is unreliable.

---

## Crowd Report

```http
POST /api/report
```

### Request

```json
{
  "user_id": 1,
  "bus_id": 1,
  "crowd_level": 4
}
```

### Crowd Levels

```text
1 = Very Low
2 = Low
3 = Moderate
4 = High
5 = Very High
```

Only values **1–5** are accepted.

---

## Bus Status

```http
GET /api/bus/{bus_id}/status
```

### Example

```text
GET /api/bus/1/status
```

Returns information such as:

* bus information
* latest GPS location
* latest speed
* active passengers
* passenger fullness
* manual-report fullness
* overall fullness
* number of reports

---

## Bus Prediction

```http
GET /api/bus/{bus_id}/prediction
```

### Example

```text
GET /api/bus/1/prediction?stop_id=1
```

### Example Response

```json
{
  "bus_id": 1,
  "stop_id": 1,
  "hour_of_day": 10,
  "day_of_week": 6,
  "live_fullness": 50.0,
  "predicted_fullness": 38.25,
  "final_fullness": 45.3,
  "status": "Leave Now",
  "message": "Bus is expected to have lower crowding."
}
```

---

# 7. Crowd Calculation

Active passengers are users with recent activity within a **5-minute window**.

The system counts **unique users**, not individual GPS pings.

### Passenger Fullness

```text
active_passengers / bus_capacity × 100
```

### Manual Crowd Conversion

```text
1 → 20%
2 → 40%
3 → 60%
4 → 80%
5 → 100%
```

The available live passenger and manual-report information is combined to calculate the current overall fullness.

---

# 8. Machine Learning

The project uses:

```text
RandomForestRegressor
```

Historical training data contains:

```text
hour_of_day
day_of_week
bus_id
stop_id
historic_fullness
```

## Train the Model

```bash
python ml/train.py
```

The trained model is saved as:

```text
ml/model.joblib
```

The model is loaded by the prediction service and is **not retrained for every API request**.

### Important

The current training dataset is **synthetic demo data**.

Therefore, the model's performance should not be interpreted as real-world bus crowd prediction accuracy.

---

# 9. Live + ML Fullness

The prediction API combines current live fullness with historical ML prediction.

### Current Prototype Weighting

```text
60% × Live Fullness
+
40% × ML Prediction
```

### Formula

```text
final_fullness =
    (live_fullness × 0.60)
    +
    (predicted_fullness × 0.40)
```

This is a simple hackathon design choice and can be modified later.

---

# 10. Recommendation Logic

The backend converts the final fullness into a recommendation.

```text
< 50%
→ Leave Now

50% – 80%
→ Moderate

> 80%
→ Leave Later

100%
→ Bus Full
```

This logic is kept separately in:

```text
app/services/notifications.py
```

---

# 11. Frontend Integration

The frontend/Tauri application only needs to communicate with the FastAPI server using HTTP requests.

### Base URL During Local Development

```text
http://127.0.0.1:8000
```

### API Examples

```text
POST http://127.0.0.1:8000/api/ping
```

```text
POST http://127.0.0.1:8000/api/checkin
```

```text
POST http://127.0.0.1:8000/api/report
```

```text
GET http://127.0.0.1:8000/api/bus/1/status
```

```text
GET http://127.0.0.1:8000/api/bus/1/prediction?stop_id=1
```

All requests and responses use **JSON**.

The frontend should **not access SQLite directly**.

All database operations go through the FastAPI backend.

---

# 12. Typical Data Flow

```text
User / Tauri App
        │
        ├── GPS
        ├── Check-in
        └── Crowd Report
                │
                ▼
             FastAPI
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
    Tracking  Crowd  Prediction
        │       │        │
        ▼       ▼        ▼
    Matching Aggregation ML Model
        │       │        │
        └───────┼────────┘
                ▼
         Final Fullness
                │
                ▼
         Recommendation
                │
                ▼
             Frontend
```

---

# 13. Testing

Run all automated tests:

```bash
pytest
```

The test suite covers:

* Health endpoint
* GPS API behavior
* Valid and invalid check-ins
* Valid and invalid crowd reports
* Bus status
* Crowd aggregation
* Prediction API
* Invalid bus IDs
* Prediction output validation

### Current Test Status

```text
10 tests passed
```

---

# 14. Database Reset

To recreate the demo database:

### Step 1

Stop the server.

### Step 2

Delete:

```text
data/bus.db
```

### Step 3

Run:

```bash
python -m app.seed
```

This recreates the synthetic routes, buses, and bus stops.

---

# 15. Important Backend Notes for the Team

* **Do not access the SQLite database directly from the frontend.**
* Use the FastAPI endpoints for all communication.
* Send JSON request bodies.
* GPS speeds below **5 km/h** are ignored.
* GPS bus matching currently uses a **30-meter threshold**.
* Active passenger data uses a **5-minute window**.
* Passengers are counted as unique users.
* Manual crowd levels are from **1 to 5**.
* The ML model is trained on **synthetic data**.
* The ML model should not be retrained during normal API requests.
* The 60/40 live-vs-prediction weighting is configurable prototype logic.
* The current system is intended as a **hackathon prototype**, not a production transit system.

---

# 16. Quick Start for Team Members

From the backend directory:

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Seed the Database

```bash
python -m app.seed
```

### 3. Train the ML Model

```bash
python ml/train.py
```

### 4. Start the Backend

```bash
uvicorn app.main:app --reload
```

### 5. Open Swagger

```text
http://127.0.0.1:8000/docs
```

### 6. Run Tests

```bash
pytest
```

---

# ✅ Backend Status

```text
Backend Foundation       ✅
SQLite Database          ✅
Demo Database            ✅
GPS Tracking             ✅
Bus Matching             ✅
Manual Check-in          ✅
Crowd Reports            ✅
Crowd Aggregation        ✅
Bus Status API           ✅
Historical Dataset       ✅
Random Forest Model      ✅
Prediction API           ✅
Live + ML Prediction     ✅
Automated Testing        ✅
Documentation            ✅
```

---

## Backend Responsibility

The backend is responsible for:

```text
GPS Data
   ↓
Bus Matching
   ↓
Passenger Tracking
   ↓
Crowd Reports
   ↓
Crowd Aggregation
   ↓
Live Fullness
   ↓
ML Prediction
   ↓
Final Fullness
   ↓
Recommendation
   ↓
JSON Response to Frontend
```



```
```
