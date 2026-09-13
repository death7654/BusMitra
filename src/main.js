const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

let greetInputEl;
let greetMsgEl;
let coordsEl;
let speedEl;
let busStatusEl;
let livePingEl;
let actionStatusEl;
let busIdInputEl;

async function greet() {
  greetMsgEl.textContent = await invoke("greet", { name: greetInputEl.value });
}

window.addEventListener("DOMContentLoaded", () => {
  greetInputEl = document.querySelector("#greet-input");
  greetMsgEl = document.querySelector("#greet-msg");
  coordsEl = document.querySelector("#coords-display");
  speedEl = document.querySelector("#speed-display");
  busStatusEl = document.querySelector("#bus-status-display");
  livePingEl = document.querySelector("#live-ping-display");
  actionStatusEl = document.querySelector("#action-status");
  busIdInputEl = document.querySelector("#bus-id-input");

  document.querySelector("#greet-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    greet();
  });

  document.getElementById("testgeo")?.addEventListener("click", () => {
    initLocation();
  });

    document.getElementById("testnotif")?.addEventListener("click", () => {
    notifyUser("Yoo this is a title", "lmao we got a body too, swag");
  });

  document.querySelector("#bus-status-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    checkBusStatus(Number(busIdInputEl.value));
  });

  document.getElementById("checkin-btn")?.addEventListener("click", () => {
    checkIn(Number(busIdInputEl.value));
  });

  document.getElementById("report-btn")?.addEventListener("click", () => {
    const level = Number(document.querySelector("#crowd-level-input").value);
    reportCrowd(Number(busIdInputEl.value), level);
  });

  // Live updates pushed from the Rust watch_position callback
  listen("location-update", (event) => {
    renderPosition(event.payload);
  });

  // Fired every time the app pings the backend with a new GPS location.
  listen("ping-update", (event) => {
    const p = event.payload;
    livePingEl.textContent = p.matched
      ? `Matched to bus #${p.bus_id} (route ${p.route_id}, ${p.distance_meters}m away)`
      : `Live GPS pings: ${p.message}`;
  });

  // Fired automatically whenever a ping matches a bus - this is the
  // "how crowded is this bus" signal computed from nearby riders.
  listen("bus-status-update", (event) => {
    renderBusStatus(event.payload);
  });
});

function renderBusStatus(status) {
  busIdInputEl.value = status.bus_id;
  const crowded = status.overall_fullness >= 80;
  busStatusEl.textContent =
    `Bus ${status.bus_number}: ${status.active_passengers} riders nearby, ` +
    `${status.overall_fullness}% full` +
    (crowded ? " — crowded, consider the next bus" : " — not crowded");
}

async function checkBusStatus(busId) {
  try {
    const status = await invoke("get_bus_status", { busId });
    renderBusStatus(status);
  } catch (err) {
    busStatusEl.textContent = `Could not load bus status: ${err}`;
  }
}

async function checkIn(busId) {
  try {
    const res = await invoke("checkin_to_bus", { busId });
    actionStatusEl.textContent = res.message;
    checkBusStatus(busId);
  } catch (err) {
    actionStatusEl.textContent = `Check-in failed: ${err}`;
  }
}

async function reportCrowd(busId, crowdLevel) {
  try {
    const res = await invoke("submit_crowd_report", { busId, crowdLevel });
    actionStatusEl.textContent = res.message;
    checkBusStatus(busId);
  } catch (err) {
    actionStatusEl.textContent = `Report failed: ${err}`;
  }
}

function renderPosition(pos) {
  coordsEl.textContent = `lat: ${pos.latitude.toFixed(6)}, lon: ${pos.longitude.toFixed(6)}`;
  speedEl.textContent =
    pos.speed_kmh == null ? "speed: —" : `speed: ${pos.speed_kmh.toFixed(1)} km/h`;
}

async function initLocation() {
  try {
    const pos = await invoke("start_location_tracking");
    console.log("User Position:", pos.latitude, pos.longitude, pos.speed_kmh);
    renderPosition(pos);
  } catch (err) {
    console.error("Location error:", err);
  }
}

async function notifyUser(title, body) {
  try {
    await invoke("send_user_notification", { title, body });
  } catch (err) {
    console.error("Notification error:", err);
  }
}