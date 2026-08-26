use serde::Serialize;
use tauri_plugin_notification::{NotificationExt, PermissionState};
use tauri_plugin_geolocation::{
    GeolocationExt, PermissionType, PositionOptions, WatchEvent,
};
use tauri::{AppHandle, Emitter};


#[derive(Serialize, Clone, Debug)]
struct PositionResponse {
    latitude: f64,
    longitude: f64,
}

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
                let coords = PositionResponse {
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude,
                };
                println!("New location update in Rust: {:?}", coords);

                let _ = app_handle.emit("location-update", coords);
            }
            WatchEvent::Error(err) => eprintln!("Error watching location: {}", err),
        })
        .map_err(|e| e.to_string())?;

        Ok(PositionResponse {
            latitude: initial_pos.coords.latitude,
            longitude: initial_pos.coords.longitude,
        })
    } else {
        Err("Location permission was denied".into())
    }
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
        .invoke_handler(tauri::generate_handler![start_location_tracking, send_user_notification])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}