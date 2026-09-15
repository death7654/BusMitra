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

# ---------------------------------------------------------
# Check-out
# ---------------------------------------------------------

def test_checkout_after_checkin():
    """A rider who checks in can check out again."""

    client.post("/api/checkin", json={"user_id": 2001, "bus_id": 1})

    response = client.post("/api/checkout", json={"user_id": 2001})

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["bus_id"] == 1
    assert data["ride_seconds"] >= 0


def test_checkout_without_checkin():
    response = client.post("/api/checkout", json={"user_id": 2002})

    assert response.status_code == 404


def test_double_checkin_is_not_two_riders():
    """
    Check-ins are sessions, so pressing the button twice must not
    open a second one - that would count one person as two.
    """

    client.post("/api/checkin", json={"user_id": 2003, "bus_id": 1})
    second = client.post("/api/checkin", json={"user_id": 2003, "bus_id": 1})

    assert second.status_code in [200, 201]

    # One check-out closes the ride; a second finds nothing open.
    assert client.post(
        "/api/checkout", json={"user_id": 2003}
    ).status_code == 200

    assert client.post(
        "/api/checkout", json={"user_id": 2003}
    ).status_code == 404


def test_checkout_drops_rider_from_count():
    before = client.get("/api/bus/1/status").json()["active_passengers"]

    client.post("/api/checkin", json={"user_id": 2004, "bus_id": 1})
    during = client.get("/api/bus/1/status").json()["active_passengers"]

    client.post("/api/checkout", json={"user_id": 2004})
    after = client.get("/api/bus/1/status").json()["active_passengers"]

    assert during == before + 1
    # The whole point of check-out: the rider leaves the count now,
    # not once the 5-minute activity window lapses.
    assert after == before


# ---------------------------------------------------------
# Adding buses
# ---------------------------------------------------------

def test_add_bus_rejects_unknown_route():
    response = client.post(
        "/api/buses",
        json={"route_id": 9999, "bus_number": "TEST-1", "capacity": 40},
    )

    assert response.status_code == 404


def test_add_bus_rejects_bad_bus_number():
    response = client.post(
        "/api/buses",
        json={"route_id": 1, "bus_number": "!!!", "capacity": 40},
    )

    assert response.status_code == 422


def test_add_bus_rejects_bad_capacity():
    response = client.post(
        "/api/buses",
        json={"route_id": 1, "bus_number": "TEST-CAP", "capacity": 0},
    )

    assert response.status_code == 422


def test_add_bus_then_duplicate_number_conflicts():
    created = client.post(
        "/api/buses",
        json={"route_id": 1, "bus_number": "TEST-DUP", "capacity": 40},
    )

    # Tests run against the real SQLite file and deletion needs an
    # admin token this suite deliberately doesn't configure, so the
    # bus survives the run. A 409 here just means a previous run
    # already created it - which is exactly the state the assertion
    # below cares about either way.
    assert created.status_code in [200, 201, 409]

    if created.status_code != 409:
        # Normalisation happens before the uniqueness check.
        assert created.json()["bus_number"] == "TEST-DUP"

    duplicate = client.post(
        "/api/buses",
        json={"route_id": 1, "bus_number": "test-dup", "capacity": 40},
    )

    assert duplicate.status_code == 409


# ---------------------------------------------------------
# Strict deletion
# ---------------------------------------------------------
#
# These assume BUSMITRA_ADMIN_TOKEN is *not* set, which is the default
# for a test run. That's the fail-closed case and the most important
# one to pin down: no configuration must mean "disabled", never "open".

def test_delete_requires_configured_token():
    response = client.delete("/api/buses/1?confirm=BUS-101-A")

    assert response.status_code == 503


def test_delete_still_refused_without_token_even_with_force():
    response = client.delete(
        "/api/buses/1?confirm=BUS-101-A&force=true"
    )

    assert response.status_code == 503


def test_delete_requires_confirm_parameter():
    """Omitting confirm is a validation error, not a deletion."""

    response = client.delete("/api/buses/1")

    assert response.status_code in [422, 503]


def test_fleet_list_shape():
    response = client.get("/api/buses")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

    if data:
        bus = data[0]
        for field in [
            "id",
            "bus_number",
            "capacity",
            "route_id",
            "route_number",
            "active_passengers",
        ]:
            assert field in bus


# ---------------------------------------------------------
# Demo mode
# ---------------------------------------------------------

def test_demo_status_reports_shape():
    response = client.get("/api/demo/status")

    assert response.status_code == 200

    data = response.json()

    assert "running" in data
    assert "available" in data
    assert data["tick_seconds"] > 0


def test_demo_reset_is_safe_when_not_running():
    """Clearing simulated data must work even if a demo never ran."""

    response = client.post("/api/demo/reset")

    assert response.status_code == 200
    assert response.json()["success"] is True


# ---------------------------------------------------------
# One report per device
# ---------------------------------------------------------

def test_second_report_is_rate_limited():
    """A device gets one vote, not one vote per tap."""

    first = client.post(
        "/api/report",
        json={"user_id": 3001, "bus_id": 1, "crowd_level": 4},
    )

    assert first.status_code in [200, 201]

    second = client.post(
        "/api/report",
        json={"user_id": 3001, "bus_id": 1, "crowd_level": 1},
    )

    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_report_returns_its_own_effect():
    """
    Reporting must show what it changed. The old endpoint returned a
    fixed string, which is why reporting felt like it did nothing.
    """

    response = client.post(
        "/api/report",
        json={"user_id": 3002, "bus_id": 2, "crowd_level": 5},
    )

    assert response.status_code in [200, 201]

    data = response.json()

    assert data["overall_fullness"] is not None
    assert data["reporter_count"] >= 1
    assert data["next_report_in_seconds"] > 0


def test_reports_move_the_number_on_a_quiet_bus():
    """
    A report on a bus with no phones aboard used to be averaged
    against a phantom 0% and halved. It must now carry the estimate.
    """

    before = client.get("/api/bus/3/status").json()

    client.post(
        "/api/report",
        json={"user_id": 3003, "bus_id": 3, "crowd_level": 5},
    )

    after = client.get("/api/bus/3/status").json()

    assert after["overall_fullness"] >= before["overall_fullness"]
    assert after["reporter_count"] >= 1
    assert after["crowd_source"] in ["reports", "blended"]


def test_status_exposes_crowd_attribution():
    data = client.get("/api/bus/1/status").json()

    for field in [
        "reporter_count",
        "passenger_weight",
        "report_weight",
        "crowd_source",
        "trend",
    ]:
        assert field in data

    assert 0.0 <= data["passenger_weight"] <= 1.0
    assert 0.0 <= data["report_weight"] <= 1.0


# ---------------------------------------------------------
# Route-aware ETA
# ---------------------------------------------------------

def test_eta_shape_and_status():
    routes = client.get("/api/routes").json()
    stop_id = routes[0]["stops"][0]["id"]
    bus_id = routes[0]["buses"][0]["id"]

    response = client.get(f"/api/bus/{bus_id}/eta?stop_id={stop_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] in [
        "approaching",
        "heading_away",
        "stopped",
        "uncertain",
        "no_data",
        "off_route",
    ]

    # Never a fabricated number: if there's no estimate there's no
    # eta_seconds, and if there is one it's positive.
    if data["eta_seconds"] is None:
        assert data["status"] != "approaching"
    else:
        assert data["eta_seconds"] >= 0


def test_eta_rejects_stop_on_another_route():
    routes = client.get("/api/routes").json()

    if len(routes) < 2:
        return

    bus_id = routes[0]["buses"][0]["id"]
    foreign_stop = routes[1]["stops"][0]["id"]

    data = client.get(
        f"/api/bus/{bus_id}/eta?stop_id={foreign_stop}"
    ).json()

    assert data["status"] == "off_route"
    assert data["eta_seconds"] is None


def test_eta_unknown_bus_is_404():
    assert client.get("/api/bus/9999/eta?stop_id=1").status_code == 404


# ---------------------------------------------------------
# Stop board
# ---------------------------------------------------------

def test_stop_board_shape():
    routes = client.get("/api/routes").json()
    stop_id = routes[0]["stops"][0]["id"]

    response = client.get(f"/api/stop/{stop_id}/arrivals")

    assert response.status_code == 200

    data = response.json()

    assert data["stop_id"] == stop_id
    assert isinstance(data["arrivals"], list)

    for arrival in data["arrivals"]:
        assert "eta" in arrival
        assert "overall_fullness" in arrival
        # A board must never list a bus that has already gone past.
        assert arrival["eta"]["status"] in ["approaching", "uncertain"]


def test_stop_board_sorted_by_arrival():
    routes = client.get("/api/routes").json()
    stop_id = routes[0]["stops"][0]["id"]

    arrivals = client.get(
        f"/api/stop/{stop_id}/arrivals?include_unknown=true"
    ).json()["arrivals"]

    seconds = [
        a["eta"]["eta_seconds"]
        for a in arrivals
        if a["eta"]["eta_seconds"] is not None
    ]

    assert seconds == sorted(seconds)


def test_stop_board_unknown_stop_is_404():
    assert client.get("/api/stop/999999/arrivals").status_code == 404

# ---------------------------------------------------------
# Evidence-weighted prediction
# ---------------------------------------------------------

def test_prediction_exposes_its_own_weighting():
    """
    A single percentage can't say whether it was measured or guessed,
    so the endpoint has to report how it was arrived at.
    """

    data = client.get("/api/bus/1/prediction?stop_id=1").json()

    for field in [
        "live_weight",
        "model_weight",
        "live_evidence",
        "confidence",
        "observed_samples",
        "explanation",
    ]:
        assert field in data

    assert 0.0 <= data["live_weight"] <= 1.0
    assert 0.0 <= data["live_evidence"] <= 1.0
    assert abs(data["live_weight"] + data["model_weight"] - 1.0) < 0.01
    assert data["confidence"] in ["high", "medium", "low", "model_only"]
    assert data["explanation"]


def test_quiet_bus_is_not_dragged_down_by_a_phantom_live_zero():
    """
    The old blend gave the live half a fixed 60% even when nothing was
    aboard to measure. Live fullness is 0.0 by construction on an
    unobserved bus, so that silently multiplied every quiet bus's
    forecast by 0.4 and presented the result as a prediction.
    """

    data = client.get("/api/bus/4/prediction?stop_id=1").json()

    if data["live_evidence"] > 0:
        return  # bus has live signal; nothing to assert here

    assert data["live_weight"] == 0.0
    assert data["confidence"] == "model_only"
    # With no live evidence the figure is the forecast, untouched.
    assert abs(data["final_fullness"] - data["predicted_fullness"]) < 0.01


def test_live_weight_never_exceeds_the_historical_share():
    """
    Full evidence must reproduce the original 60/40 split, not exceed
    it. The live signal is a headcount of app users, which systematically
    undercounts - it should never own the whole number.
    """

    routes = client.get("/api/routes").json()

    for route in routes:
        for bus in route["buses"]:
            data = client.get(
                f"/api/bus/{bus['id']}/prediction?stop_id="
                f"{route['stops'][0]['id']}"
            ).json()

            assert data["live_weight"] <= 0.6 + 1e-9


# ---------------------------------------------------------
# Model provenance
# ---------------------------------------------------------

def test_model_info_reports_what_it_was_trained_on():
    response = client.get("/api/model/info")

    assert response.status_code == 200

    data = response.json()

    assert data["available"] is True
    assert data["trained_on"] in ["synthetic", "synthetic+observed"]
    assert data["synthetic_rows"] > 0
    assert 0.0 <= data["real_row_share"] <= 1.0
    assert data["features"]

    # A model trained on nothing real must not claim otherwise.
    if data["trained_on"] == "synthetic":
        assert data["real_rows"] == 0
        assert data["real_row_share"] == 0.0


def test_model_info_reports_observation_backlog():
    data = client.get("/api/model/info").json()["observations"]

    assert data["real_observations"] >= 0
    assert data["simulated_observations"] >= 0
    assert data["sample_interval_seconds"] > 0
    assert 0.0 < data["min_evidence"] <= 1.0


# ---------------------------------------------------------
# Observation recording
# ---------------------------------------------------------

def test_observation_is_refused_without_evidence():
    """
    The single most important rule in the learning loop: a bus with
    nobody aboard measures as 0% full, and recording that would teach
    the model the whole fleet runs empty.
    """

    from app.database import SessionLocal
    from app.models import Bus
    from app.services.observations import record_observation

    db = SessionLocal()

    try:
        bus = db.query(Bus).first()

        row = record_observation(
            db=db,
            bus=bus,
            crowd={
                "overall_fullness": 0.0,
                "passenger_weight": 0.0,
                "report_weight": 0.0,
                "active_passengers": 0,
                "reporter_count": 0,
                "crowd_source": "none",
            },
            simulated=False,
        )

        assert row is None
    finally:
        db.rollback()
        db.close()


def test_observation_is_kept_when_evidence_is_real():
    from app.database import SessionLocal
    from app.models import Bus, CrowdObservation
    from app.services.observations import record_observation

    db = SessionLocal()

    try:
        bus = db.query(Bus).first()

        # Clear the cooldown so the test doesn't depend on when the
        # background sampler last ran.
        db.query(CrowdObservation).filter(
            CrowdObservation.bus_id == bus.id
        ).delete(synchronize_session=False)
        db.commit()

        row = record_observation(
            db=db,
            bus=bus,
            crowd={
                "overall_fullness": 72.5,
                "passenger_weight": 0.6,
                "report_weight": 0.4,
                "active_passengers": 3,
                "reporter_count": 2,
                "crowd_source": "blended",
            },
            simulated=False,
        )

        assert row is not None
        assert row.observed_fullness == 72.5
        assert row.is_simulated == 0
        assert 0.0 < row.evidence <= 1.0
        assert 0 <= row.hour_of_day <= 23
        assert 0 <= row.day_of_week <= 6
    finally:
        db.rollback()
        db.close()


def test_observations_are_not_recorded_twice_in_quick_succession():
    """
    A sampler running every couple of minutes must not be able to fill
    the table with near-identical rows that then dominate training.
    """

    from app.database import SessionLocal
    from app.models import Bus, CrowdObservation
    from app.services.observations import record_observation

    db = SessionLocal()

    crowd = {
        "overall_fullness": 60.0,
        "passenger_weight": 0.5,
        "report_weight": 0.5,
        "active_passengers": 2,
        "reporter_count": 2,
        "crowd_source": "blended",
    }

    try:
        bus = db.query(Bus).first()

        db.query(CrowdObservation).filter(
            CrowdObservation.bus_id == bus.id
        ).delete(synchronize_session=False)
        db.commit()

        assert record_observation(
            db=db, bus=bus, crowd=crowd, simulated=False
        ) is not None
        db.commit()

        assert record_observation(
            db=db, bus=bus, crowd=crowd, simulated=False
        ) is None
    finally:
        db.query(CrowdObservation).filter(
            CrowdObservation.bus_id == bus.id
        ).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_simulated_observations_are_tagged_and_purgeable():
    """
    Demo data must never reach the training set. It's tagged on write
    and removed by the same purge that clears the rest of the demo.
    """

    from app.database import SessionLocal
    from app.models import Bus, CrowdObservation
    from app.services.observations import (
        purge_simulated_observations,
        record_observation,
    )

    db = SessionLocal()

    try:
        bus = db.query(Bus).first()

        db.query(CrowdObservation).filter(
            CrowdObservation.bus_id == bus.id
        ).delete(synchronize_session=False)
        db.commit()

        row = record_observation(
            db=db,
            bus=bus,
            crowd={
                "overall_fullness": 90.0,
                "passenger_weight": 0.9,
                "report_weight": 0.1,
                "active_passengers": 5,
                "reporter_count": 1,
                "crowd_source": "blended",
            },
            simulated=True,
        )

        assert row is not None
        assert row.is_simulated == 1

        db.commit()

        purge_simulated_observations(db)

        assert (
            db.query(CrowdObservation)
            .filter(CrowdObservation.is_simulated == 1)
            .count()
            == 0
        )
    finally:
        db.close()


# ---------------------------------------------------------
# Model loading
# ---------------------------------------------------------

def test_model_path_does_not_depend_on_the_working_directory():
    """
    The model path used to be relative to the process working
    directory, so launching uvicorn from the repo root instead of
    backend/ turned every prediction into a 500.
    """

    import os

    from app.services.prediction import predict_fullness

    original = os.getcwd()

    try:
        os.chdir("/")

        value = predict_fullness(
            bus_id=1, stop_id=1, hour_of_day=8, day_of_week=1
        )

        assert 0 <= value <= 100
    finally:
        os.chdir(original)


def test_repeated_predictions_reuse_the_loaded_model():
    """
    A forecast request calls the model 31 times. Reloading a 100-tree
    forest from disk each time cost well over a second per request.
    """

    from app.services import prediction

    prediction.load_prediction_model()
    first, _ = prediction.load_prediction_model()
    second, _ = prediction.load_prediction_model()

    assert first is second


def test_forecast_still_returns_a_full_day_and_week():
    response = client.get("/api/bus/1/forecast?stop_id=1")

    assert response.status_code == 200

    data = response.json()

    assert len(data["hourly"]) == 24
    assert len(data["weekly"]) == 7
    assert all(0 <= p["predicted_fullness"] <= 100 for p in data["hourly"])