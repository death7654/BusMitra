const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

let greetInputEl;
let greetMsgEl;
let coordsEl;

async function greet() {
  greetMsgEl.textContent = await invoke("greet", { name: greetInputEl.value });
}

window.addEventListener("DOMContentLoaded", () => {
  greetInputEl = document.querySelector("#greet-input");
  greetMsgEl = document.querySelector("#greet-msg");
  coordsEl = document.querySelector("#coords-display");

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

  // Live updates pushed from the Rust watch_position callback
  listen("location-update", (event) => {
    const { latitude, longitude } = event.payload;
    coordsEl.textContent = `lat: ${latitude.toFixed(6)}, lon: ${longitude.toFixed(6)}`;
  });
});

async function initLocation() {
  try {
    const pos = await invoke("start_location_tracking");
    console.log("User Position:", pos.latitude, pos.longitude);
    coordsEl.textContent = `lat: ${pos.latitude.toFixed(6)}, lon: ${pos.longitude.toFixed(6)}`;
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