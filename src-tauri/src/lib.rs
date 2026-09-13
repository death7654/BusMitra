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
const API_BASE_URL: &str = "http://10.0.2.2:8000";

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
struct CrowdReportResponse {
    success: bool,
    user_id: i64,
    bus_id: i64,
    crowd_level: i32,
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
}

#[derive(Serialize, Deserialize, Clone, Debug)]
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
}

// -----------------------------------------------------------------------
// Internal HTTP helpers (used by both Tauri commands and the background
// location watcher)
// -----------------------------------------------------------------------

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

    res.json::<CheckInResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected check-in response: {e}"))
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

    res.json::<CrowdReportResponse>()
        .await
        .map_err(|e| format!("Backend returned an unexpected report response: {e}"))
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
            start_location_tracking,
            send_user_notification,
            checkin_to_bus,
            submit_crowd_report,
            get_bus_status,
            get_bus_prediction,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}