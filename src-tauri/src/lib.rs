use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri_plugin_notification::{NotificationExt, PermissionState};
use tauri_plugin_geolocation::{
    GeolocationExt, PermissionType, PositionOptions, WatchEvent,
};
use tauri_plugin_http::reqwest;
use tauri::{AppHandle, Emitter, Manager};

// -----------------------------------------------------------------------
// Backend configuration
// -----------------------------------------------------------------------
// Desktop (Windows/macOS/Linux): 127.0.0.1 reaches the FastAPI server
// running on the same machine.
// Android emulator: the emulator's loopback to the host machine is
// 10.0.2.2, not 127.0.0.1 - swap the constant below when testing on it.
// Physical device: use your machine's LAN IP (e.g. http://192.168.x.x:8000)
// and make sure the phone is on the same network.
//  const API_BASE_URL: &str = "http://10.0.2.2:8000";

const API_BASE_URL: &str = "http://192.168.137.1:8000";

// -----------------------------------------------------------------------
// App state
// -----------------------------------------------------------------------
// Anonymous per-install user id, generated once at startup, used to
// identify this device's pings/check-ins/reports to the backend.
struct AppState {
    user_id: i64,
}

fn generate_user_id() -> i64 {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    // Backend requires user_id > 0.
    ((nanos % 1_000_000_000) as i64) + 1
}

// -----------------------------------------------------------------------
// Backend response/request shapes (mirrors backend/app/schemas.py)
// -----------------------------------------------------------------------

#[derive(Serialize, Clone, Debug)]
struct PositionResponse {
    latitude: f64,
    longitude: f64,
    // Ground speed in km/h, converted from the raw m/s the Geolocation
    // API reports. None if the device hasn't provided a speed reading yet.
    speed_kmh: Option<f64>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct PingResponse {
    accepted: bool,
    matched: bool,
    bus_id: Option<i64>,
    route_id: Option<i64>,
    nearest_stop_id: Option<i64>,
    distance_meters: Option<f64>,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct CheckInResponse {
    success: bool,
    user_id: i64,
    bus_id: i64,
    bus_number: String,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct CheckOutResponse {
    success: bool,
    user_id: i64,
    bus_id: i64,
    bus_number: String,
    checked_in_at: String,
    checked_out_at: String,
    ride_seconds: i64,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BusOut {
    id: i64,
    bus_number: String,
    capacity: i32,
    route_id: i64,
    route_number: String,
    route_name: String,
    active_passengers: i32,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BusDeleteResponse {
    success: bool,
    bus_id: i64,
    bus_number: String,
    deleted_pings: i32,
    deleted_checkins: i32,
    deleted_reports: i32,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct DemoBusState {
    bus_id: i64,
    bus_number: String,
    latitude: f64,
    longitude: f64,
    speed_kmh: f64,
    simulated_riders: i32,
    capacity: i32,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct DemoStatusResponse {
    available: bool,
    running: bool,
    started_at: Option<String>,
    ticks: i64,
    tick_seconds: f64,
    simulated_buses: Vec<DemoBusState>,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct DemoResetResponse {
    success: bool,
    deleted_pings: i32,
    deleted_checkins: i32,
    deleted_reports: i32,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct CrowdReportResponse {
    success: bool,
    user_id: i64,
    bus_id: i64,
    crowd_level: i32,
    message: String,
    #[serde(default)]
    overall_fullness: Option<f64>,
    #[serde(default)]
    reporter_count: i32,
    #[serde(default)]
    replaced_previous: bool,
    #[serde(default)]
    next_report_in_seconds: i32,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct EtaResponse {
    bus_id: i64,
    stop_id: i64,
    status: String,
    message: String,
    eta_seconds: Option<i64>,
    eta_minutes: Option<f64>,
    eta_max_seconds: Option<i64>,
    distance_meters: Option<f64>,
    straight_line_meters: Option<f64>,
    speed_kmh: Option<f64>,
    stops_away: Option<i32>,
    off_route_meters: Option<f64>,
    sample_count: i32,
    confidence: String,

    // Added with the Kalman filter. serde defaults so an older
    // backend that doesn't send them still deserialises rather than
    // failing the whole response.
    #[serde(default)]
    eta_min_seconds: Option<i64>,
    #[serde(default)]
    velocity_std_ms: Option<f64>,
    #[serde(default)]
    learned_traffic_share: f64,
    #[serde(default)]
    dwell_seconds: Option<f64>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct StopArrival {
    bus_id: i64,
    bus_number: String,
    route_id: i64,
    route_number: String,
    route_name: String,
    eta: EtaResponse,
    overall_fullness: f64,
    crowd_source: String,
    trend: String,
    active_passengers: i32,
    reporter_count: i32,
    capacity: i32,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct StopBoardResponse {
    stop_id: i64,
    stop_name: String,
    generated_at: String,
    arrivals: Vec<StopArrival>,
    message: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BusStatusResponse {
    bus_id: i64,
    bus_number: String,
    route_id: i64,
    latest_latitude: Option<f64>,
    latest_longitude: Option<f64>,
    latest_speed: Option<f64>,
    latest_timestamp: Option<String>,
    // Unique nearby riders detected in the last 5 minutes - this is the
    // "how many people are close by" crowd signal.
    active_passengers: i32,
    passenger_fullness: f64,
    manual_fullness: Option<f64>,
    overall_fullness: f64,
    report_count: i32,
    // Attribution for the figure above. Defaulted so an older backend
    // that doesn't send them still deserialises.
    #[serde(default)]
    reporter_count: i32,
    #[serde(default)]
    passenger_weight: f64,
    #[serde(default)]
    report_weight: f64,
    #[serde(default)]
    crowd_source: String,
    #[serde(default)]
    trend: String,
}

/// The headline crowd figure, plus how it was arrived at.
///
/// The backend no longer blends live data with the model at a fixed
/// 60/40 - the live half is weighted by how much evidence sits behind
/// it, which is zero on a bus nobody is riding with the app. The
/// weighting fields carry that through to the UI so a measurement and
/// a guess don't render identically.
///
/// `#[serde(default)]` keeps a newer client working against an older
/// backend: the fields fall back to zero rather than turning the whole
/// response into a deserialisation error.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
#[serde(default)]
struct BusPredictionResponse {
    bus_id: i64,
    stop_id: i64,
    hour_of_day: i32,
    day_of_week: i32,
    live_fullness: f64,
    predicted_fullness: f64,
    final_fullness: f64,
    status: String,
    message: String,

    /// Share of the final figure taken from live signals (0.0-1.0).
    live_weight: f64,
    /// Share taken from the ML forecast. Sums to 1.0 with live_weight.
    model_weight: f64,
    /// Raw evidence score behind the live half, before it is scaled.
    live_evidence: f64,
    /// "high" | "medium" | "low" | "model_only".
    confidence: String,
    /// Real observations of this bus in the model's training set.
    observed_samples: i32,
    /// One-line plain-language account of the blend.
    explanation: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct RouteStopResponse {
    id: i64,
    name: String,
    latitude: f64,
    longitude: f64,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct RouteBusResponse {
    id: i64,
    bus_number: String,
    capacity: i32,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct RouteResponse {
    route_id: i64,
    route_number: String,
    route_name: String,
    stops: Vec<RouteStopResponse>,
    buses: Vec<RouteBusResponse>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct ForecastPoint {
    hour_of_day: i32,
    predicted_fullness: f64,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct ForecastDayPoint {
    day_of_week: i32,
    predicted_fullness: f64,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BusForecastResponse {
    bus_id: i64,
    stop_id: i64,
    hourly: Vec<ForecastPoint>,
    weekly: Vec<ForecastDayPoint>,
}

// -----------------------------------------------------------------------
// Internal HTTP helpers (used by both Tauri commands and the background
// location watcher)
// -----------------------------------------------------------------------

/// Decode a backend response, turning non-2xx replies into readable
/// errors instead of confusing deserialisation failures.
///
/// The admin endpoints deliberately reject requests with a 400/401/
/// 409/423 and an explanation in FastAPI's `detail` field - "this bus
/// still has 12 riders on board" is the whole point of asking. Calling
/// `res.json::<T>()` straight away would throw that away and surface
/// "missing field `success`" to the user instead.
async fn json_or_error<T: serde::de::DeserializeOwned>(
    res: reqwest::Response,
    what: &str,
) -> Result<T, String> {
    let status = res.status();

    let body = res
        .text()
        .await
        .map_err(|e| format!("Could not read the {what} response: {e}"))?;

    if !status.is_success() {
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&body) {
            if let Some(detail) = value.get("detail") {
                // FastAPI uses a plain string for HTTPException and a
                // list of objects for request-validation failures.
                let message = match detail.as_str() {
                    Some(text) => text.to_string(),
                    None => detail
                        .as_array()
                        .and_then(|errors| errors.first())
                        .and_then(|first| first.get("msg"))
                        .and_then(|msg| msg.as_str())
                        .map(|msg| msg.to_string())
                        .unwrap_or_else(|| detail.to_string()),
                };

                return Err(message);
            }
        }

        return Err(format!(
            "Backend returned {status} for {what}."
        ));
    }

    serde_json::from_str::<T>(&body)
        .map_err(|e| format!("Backend returned an unexpected {what} response: {e}"))
}

async fn send_gps_ping_internal(
    user_id: i64,
    latitude: f64,
    longitude: f64,
    speed_kmh: f64,
) -> Result<PingResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/ping"))
        .json(&serde_json::json!({
            "user_id": user_id,
            "latitude": latitude,
            "longitude": longitude,
            "speed": speed_kmh,
        }))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    res.json::<PingResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected ping response: {e}"))
}

async fn get_bus_status_internal(bus_id: i64) -> Result<BusStatusResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/bus/{bus_id}/status"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    res.json::<BusStatusResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected status response: {e}"))
}

// -----------------------------------------------------------------------
// Tauri commands - invoked from the frontend
// -----------------------------------------------------------------------

#[tauri::command]
async fn start_location_tracking(app: AppHandle) -> Result<PositionResponse, String> {
    let geo = app.geolocation();

    let mut permissions = geo.check_permissions().map_err(|e| e.to_string())?;

    if permissions.location == PermissionState::Prompt
        || permissions.location == PermissionState::PromptWithRationale
    {
        permissions = geo
            .request_permissions(Some(vec![PermissionType::Location]))
            .map_err(|e| e.to_string())?;
    }

    if permissions.location == PermissionState::Granted {
        let options = PositionOptions {
            enable_high_accuracy: true,
            timeout: 10000,
            maximum_age: 0,
        };

        let initial_pos = geo
            .get_current_position(Some(options.clone()))
            .map_err(|e| e.to_string())?;

        let app_handle = app.clone();
        geo.watch_position(options, move |event| match event {
            WatchEvent::Position(pos) => {
                // Web/mobile Geolocation speed is in m/s; backend and UI expect km/h.
                let speed_kmh = pos.coords.speed.map(|s| s * 3.6);
                let coords = PositionResponse {
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude,
                    speed_kmh,
                };
                println!("New location update in Rust: {:?}", coords);

                let _ = app_handle.emit("location-update", coords.clone());

                // Forward every location update to the backend as a GPS
                // ping. The backend matches it to a nearby bus and counts
                // it toward that bus's active-rider (crowding) total.
                let user_id = app_handle.state::<AppState>().user_id;
                let speed_kmh = speed_kmh.unwrap_or(0.0);
                let latitude = coords.latitude;
                let longitude = coords.longitude;
                let ping_handle = app_handle.clone();

                tauri::async_runtime::spawn(async move {
                    match send_gps_ping_internal(user_id, latitude, longitude, speed_kmh).await {
                        Ok(ping) => {
                            let _ = ping_handle.emit("ping-update", ping.clone());

                            // If this ping matched a bus, immediately pull
                            // that bus's live crowd status so the UI can
                            // show whether it's crowded right now.
                            if let Some(bus_id) = ping.bus_id {
                                match get_bus_status_internal(bus_id).await {
                                    Ok(status) => {
                                        let _ = ping_handle.emit("bus-status-update", status);
                                    }
                                    Err(e) => eprintln!("Failed to fetch bus status: {e}"),
                                }
                            }
                        }
                        Err(e) => eprintln!("Failed to send GPS ping to backend: {e}"),
                    }
                });
            }
            WatchEvent::Error(err) => eprintln!("Error watching location: {}", err),
        })
        .map_err(|e| e.to_string())?;

        Ok(PositionResponse {
            latitude: initial_pos.coords.latitude,
            longitude: initial_pos.coords.longitude,
            speed_kmh: initial_pos.coords.speed.map(|s| s * 3.6),
        })
    } else {
        Err("Location permission was denied".into())
    }
}

#[tauri::command]
async fn checkin_to_bus(app: AppHandle, bus_id: i64) -> Result<CheckInResponse, String> {
    let user_id = app.state::<AppState>().user_id;
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/checkin"))
        .json(&serde_json::json!({ "user_id": user_id, "bus_id": bus_id }))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<CheckInResponse>(res, "check-in").await
}

#[tauri::command]
async fn checkout_from_bus(
    app: AppHandle,
    bus_id: Option<i64>,
) -> Result<CheckOutResponse, String> {
    let user_id = app.state::<AppState>().user_id;
    let client = reqwest::Client::new();

    // bus_id is optional: with it omitted the backend closes whichever
    // ride is currently open, which is what the "Check out" button in
    // the tracking panel wants when the user never picked a bus by
    // hand and was matched by GPS instead.
    let mut payload = serde_json::json!({ "user_id": user_id });

    if let Some(id) = bus_id {
        payload["bus_id"] = serde_json::json!(id);
    }

    let res = client
        .post(format!("{API_BASE_URL}/api/checkout"))
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<CheckOutResponse>(res, "check-out").await
}

// -----------------------------------------------------------------------
// Fleet administration
// -----------------------------------------------------------------------

#[tauri::command]
async fn list_buses() -> Result<Vec<BusOut>, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/buses"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<Vec<BusOut>>(res, "fleet list").await
}

#[tauri::command]
async fn create_bus(
    route_id: i64,
    bus_number: String,
    capacity: i32,
    admin_token: Option<String>,
) -> Result<BusOut, String> {
    let client = reqwest::Client::new();

    let mut request = client
        .post(format!("{API_BASE_URL}/api/buses"))
        .json(&serde_json::json!({
            "route_id": route_id,
            "bus_number": bus_number,
            "capacity": capacity,
        }));

    // Only sent when the user supplied one. The backend treats an
    // unconfigured token as "open" for creation, so a fresh dev setup
    // works without any configuration at all.
    if let Some(token) = admin_token.filter(|t| !t.trim().is_empty()) {
        request = request.header("X-Admin-Token", token);
    }

    let res = request
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<BusOut>(res, "add bus").await
}

#[tauri::command]
async fn delete_bus(
    bus_id: i64,
    confirm: String,
    force: bool,
    admin_token: String,
) -> Result<BusDeleteResponse, String> {
    let client = reqwest::Client::new();

    // Everything that decides whether this deletion is allowed lives
    // on the server: the token check, the confirm/bus_number match,
    // the active-rider block and the force requirement. Nothing here
    // pre-empts any of it - the client just relays the answer.
    let res = client
        .delete(format!("{API_BASE_URL}/api/buses/{bus_id}"))
        .query(&[
            ("confirm", confirm),
            ("force", force.to_string()),
        ])
        .header("X-Admin-Token", admin_token)
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<BusDeleteResponse>(res, "delete bus").await
}

// -----------------------------------------------------------------------
// Demo mode
// -----------------------------------------------------------------------

#[tauri::command]
async fn get_demo_status() -> Result<DemoStatusResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/demo/status"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<DemoStatusResponse>(res, "demo status").await
}

#[tauri::command]
async fn start_demo() -> Result<DemoStatusResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/demo/start"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<DemoStatusResponse>(res, "demo start").await
}

#[tauri::command]
async fn stop_demo(purge: bool) -> Result<DemoStatusResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/demo/stop"))
        .query(&[("purge", purge.to_string())])
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<DemoStatusResponse>(res, "demo stop").await
}

#[tauri::command]
async fn reset_demo() -> Result<DemoResetResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/demo/reset"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<DemoResetResponse>(res, "demo reset").await
}

#[tauri::command]
async fn submit_crowd_report(
    app: AppHandle,
    bus_id: i64,
    crowd_level: i32,
) -> Result<CrowdReportResponse, String> {
    let user_id = app.state::<AppState>().user_id;
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{API_BASE_URL}/api/report"))
        .json(&serde_json::json!({
            "user_id": user_id,
            "bus_id": bus_id,
            "crowd_level": crowd_level,
        }))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    // The backend answers a too-frequent report with 429 and an
    // explanation naming the wait, which is worth showing verbatim.
    json_or_error::<CrowdReportResponse>(res, "crowd report").await
}

#[tauri::command]
async fn get_bus_eta(bus_id: i64, stop_id: i64) -> Result<EtaResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!(
            "{API_BASE_URL}/api/bus/{bus_id}/eta?stop_id={stop_id}"
        ))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<EtaResponse>(res, "arrival estimate").await
}

#[tauri::command]
async fn get_stop_arrivals(
    stop_id: i64,
    include_unknown: bool,
) -> Result<StopBoardResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/stop/{stop_id}/arrivals"))
        .query(&[("include_unknown", include_unknown.to_string())])
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<StopBoardResponse>(res, "stop board").await
}

#[tauri::command]
async fn get_bus_status(bus_id: i64) -> Result<BusStatusResponse, String> {
    get_bus_status_internal(bus_id).await
}

#[tauri::command]
async fn get_bus_prediction(bus_id: i64, stop_id: i64) -> Result<BusPredictionResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!(
            "{API_BASE_URL}/api/bus/{bus_id}/prediction?stop_id={stop_id}"
        ))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    res.json::<BusPredictionResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected prediction response: {e}"))
}

#[tauri::command]
async fn get_routes() -> Result<Vec<RouteResponse>, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/routes"))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    res.json::<Vec<RouteResponse>>()
        .await
        .map_err(|e| format!("Backend returned an unexpected routes response: {e}"))
}

#[tauri::command]
async fn get_bus_forecast(bus_id: i64, stop_id: i64) -> Result<BusForecastResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!(
            "{API_BASE_URL}/api/bus/{bus_id}/forecast?stop_id={stop_id}"
        ))
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    res.json::<BusForecastResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected forecast response: {e}"))
}

#[tauri::command]
async fn send_user_notification(
    app: AppHandle,
    title: String,
    body: String,
) -> Result<(), String> {
    let notification = app.notification();

    let permission = notification.permission_state().map_err(|e| e.to_string())?;

    let granted = if permission == PermissionState::Granted {
        true
    } else if permission == PermissionState::Prompt
        || permission == PermissionState::PromptWithRationale
    {
        notification.request_permission().map_err(|e| e.to_string())? == PermissionState::Granted
    } else {
        false
    };

    if !granted {
        return Err("Notification permission was denied".into());
    }

    notification
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|e| e.to_string())?;

    Ok(())
}

// -----------------------------------------------------------------------
// Batch fleet status
// -----------------------------------------------------------------------
// One request for every bus on screen instead of three per bus. The
// Predict page was making fifteen round trips to draw five buses, and
// repeating all fifteen on every refresh. Beyond the cost, the old
// shape was subtly wrong: fifteen calls observe fifteen different
// moments, so a bus's crowd figure could be drawn against an arrival
// time measured seconds apart from it.

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BatchBusState {
    bus_id: i64,
    bus_number: String,
    route_id: i64,
    capacity: i32,

    latest_latitude: Option<f64>,
    latest_longitude: Option<f64>,
    latest_speed: Option<f64>,
    latest_timestamp: Option<String>,

    active_passengers: i32,
    passenger_fullness: f64,
    manual_fullness: Option<f64>,
    overall_fullness: f64,
    report_count: i32,
    #[serde(default)]
    reporter_count: i32,
    #[serde(default)]
    passenger_weight: f64,
    #[serde(default)]
    report_weight: f64,
    #[serde(default)]
    crowd_source: String,
    #[serde(default)]
    trend: String,

    // Absent when the request named no stop - neither an arrival nor a
    // stop-specific prediction means anything without one.
    eta: Option<EtaResponse>,
    prediction: Option<BusPredictionResponse>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct BatchStatusResponse {
    generated_at: String,
    stop_id: Option<i64>,
    buses: Vec<BatchBusState>,
    #[serde(default)]
    missing_bus_ids: Vec<i64>,
}

#[tauri::command]
async fn get_batch_status(
    bus_ids: Vec<i64>,
    stop_id: Option<i64>,
) -> Result<BatchStatusResponse, String> {
    if bus_ids.is_empty() {
        return Err("No buses requested.".to_string());
    }

    let ids = bus_ids
        .iter()
        .map(|id| id.to_string())
        .collect::<Vec<_>>()
        .join(",");

    let client = reqwest::Client::new();
    let mut request = client
        .get(format!("{API_BASE_URL}/api/buses/status"))
        .query(&[("bus_ids", ids)]);

    if let Some(stop) = stop_id {
        request = request.query(&[("stop_id", stop.to_string())]);
    }

    let res = request
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<BatchStatusResponse>(res, "batch status").await
}

// The webview opens the SSE stream itself with EventSource rather than
// having Rust proxy it. EventSource already implements reconnection
// and backoff correctly, and proxying would mean reimplementing both
// in Rust and then inventing an event protocol to forward the frames.
// All the webview is missing is the address, which only Rust knows.
#[tauri::command]
fn get_api_base_url() -> String {
    API_BASE_URL.to_string()
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct JourneyLegOut {
    route_id: i64,
    route_number: String,
    route_name: String,
    board_stop_id: i64,
    board_stop_name: String,
    alight_stop_id: i64,
    alight_stop_name: String,
    stops_count: i32,
    #[serde(default)]
    bus_ids: Vec<i64>,
    best_bus_id: Option<i64>,
    best_bus_number: Option<String>,
    eta_seconds: Option<i64>,
    #[serde(default)]
    eta_status: String,
    overall_fullness: Option<f64>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct JourneyOption {
    legs: Vec<JourneyLegOut>,
    transfers: i32,
    total_stops: i32,
    first_departure_seconds: Option<i64>,
    score: f64,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct JourneyPlanResponse {
    from_stop: String,
    to_stop: String,
    generated_at: String,
    options: Vec<JourneyOption>,
    message: String,
}

// Journeys that need a change of bus. The Predict page's own search is
// a direct-route scan done in JavaScript, which is fine as far as it
// goes and goes exactly as far as one bus.
#[tauri::command]
async fn plan_journey(
    from_stop: String,
    to_stop: String,
) -> Result<JourneyPlanResponse, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(format!("{API_BASE_URL}/api/journey"))
        .query(&[("from_stop", from_stop), ("to_stop", to_stop)])
        .send()
        .await
        .map_err(|e| format!("Could not reach backend at {API_BASE_URL}: {e}"))?;

    json_or_error::<JourneyPlanResponse>(res, "journey plan").await
}
#[cfg_attr(mobile, tauri::mobile_entry_point)]

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_geolocation::init())
        .plugin(tauri_plugin_notification::init())
        .manage(AppState {
            user_id: generate_user_id(),
        })
        .invoke_handler(tauri::generate_handler![
            get_batch_status,
            get_api_base_url,
            plan_journey,
            start_location_tracking,
            send_user_notification,
            checkin_to_bus,
            checkout_from_bus,
            submit_crowd_report,
            get_bus_status,
            get_bus_eta,
            get_stop_arrivals,
            get_bus_prediction,
            get_routes,
            get_bus_forecast,
            list_buses,
            create_bus,
            delete_bus,
            get_demo_status,
            start_demo,
            stop_demo,
            reset_demo,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}