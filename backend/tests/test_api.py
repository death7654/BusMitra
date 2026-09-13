from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_invalid_bus_status():
    response = client.get("/api/bus/999/status")

    assert response.status_code == 404


def test_invalid_bus_prediction():
    response = client.get("/api/bus/999/prediction")

    assert response.status_code == 404


def test_invalid_crowd_level_zero():
    response = client.post(
        "/api/report",
        json={
            "user_id": 1001,
            "bus_id": 1,
            "crowd_level": 0,
        },
    )

    assert response.status_code == 422


def test_invalid_crowd_level_six():
    response = client.post(
        "/api/report",
        json={
            "user_id": 1002,
            "bus_id": 1,
            "crowd_level": 6,
        },
    )

    assert response.status_code == 422


def test_valid_crowd_report():
    response = client.post(
        "/api/report",
        json={
            "user_id": 1003,
            "bus_id": 1,
            "crowd_level": 3,
        },
    )

    assert response.status_code in [200, 201]


def test_valid_checkin():
    response = client.post(
        "/api/checkin",
        json={
            "user_id": 1004,
            "bus_id": 1,
        },
    )

    assert response.status_code in [200, 201]


def test_invalid_checkin_bus():
    response = client.post(
        "/api/checkin",
        json={
            "user_id": 1005,
            "bus_id": 999,
        },
    )

    assert response.status_code == 404


def test_bus_status():
    response = client.get("/api/bus/1/status")

    assert response.status_code == 200

    data = response.json()

    assert data["bus_id"] == 1
    assert "active_passengers" in data
    assert "passenger_fullness" in data
    assert "overall_fullness" in data


def test_bus_prediction():
    response = client.get(
        "/api/bus/1/prediction?stop_id=1"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["bus_id"] == 1
    assert 0 <= data["predicted_fullness"] <= 100
    assert 0 <= data["final_fullness"] <= 100
    assert data["status"] in [
        "Leave Now",
        "Moderate",
        "Leave Later",
        "Bus Full",
    ]