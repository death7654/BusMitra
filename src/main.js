const { invoke } = window.__TAURI__.core;

let greetInputEl;
let greetMsgEl;

async function greet() {
  greetMsgEl.textContent = await invoke("greet", { name: greetInputEl.value });
}

window.addEventListener("DOMContentLoaded", () => {
  greetInputEl = document.querySelector("#greet-input");
  greetMsgEl = document.querySelector("#greet-msg");
  document.querySelector("#greet-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    greet();
  });

  document.getElementById("test")?.addEventListener('click', () => {
    initLocation();
  });
});

// Geolocation via Direct IPC
async function initLocation() {
  try {
      const pos = await invoke('plugin:geolocation|getCurrentPosition');
      console.log('User Position:', pos.coords.latitude, pos.coords.longitude);
  } catch (err) {
    console.error('Location error:', err);
  }
}

// Notifications via Direct IPC
async function notifyUser(title, body) {
  try {
    let granted = await invoke('plugin:notification|is_permission_granted');
    if (!granted) {
      const status = await invoke('plugin:notification|request_permission');
      granted = status === 'granted';
    }

    if (granted) {
      await invoke('plugin:notification|notify', {
        options: { title, body }
      });
    }
  } catch (err) {
    console.error('Notification error:', err);
  }
}