const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

// ---------------------------------------------------------------------
// Status -> color mapping (matches backend/app/services/prediction.py
// get_prediction_status thresholds exactly, so colors never disagree
// with the text the backend actually returned).
// ---------------------------------------------------------------------
const STATUS_COLOR = {
  "Leave Now": "var(--green)",
  "Moderate": "var(--yellow)",
  "Leave Later": "var(--orange)",
  "Bus Full": "var(--red)",
};
function colorFor(status) {
  return STATUS_COLOR[status] || "var(--muted)";
}
// The backend no longer blends live data with the model at a fixed
// 60/40. It weights the live half by how much evidence sits behind it,
// and reports that weight - so these labels describe what the number
// actually is rather than asserting a confidence the API never gave.
// Mirrors confidence_label() in backend/app/services/prediction.py.
const CONFIDENCE_LABEL = {
  high: "Mostly measured",
  medium: "Part measured, part forecast",
  low: "Mostly forecast",
  model_only: "Forecast only",
};

function bandColor(pct) {

  if (pct > 80) return "var(--red)";
  if (pct >= 50) return "var(--yellow)";
  return "var(--green)";
}

// Bus numbers and route names now come from user input (Add bus), so
// anything interpolated into innerHTML gets escaped first.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}

// ---------------------------------------------------------------------
// State
// ---------------------------------------------------------------------
let routes = [];        // from get_routes
let candidates = [];    // computed per Predict click
let selectedBusId = null;
let trackingStarted = false;
let lastNotifiedStatus = new Map(); // bus_id -> last status we already notified about

// Fleet management
let fleet = [];
let adminToken = "";
let pendingDeleteId = null;    // bus whose confirm row is open
let deleteNeedsForce = false;  // backend told us history is attached
let deleteTypedValue = "";     // preserved across re-renders

// The ride the user is currently checked in to, so the same button can
// offer Check in or Check out without guessing.
let currentRide = null; // { bus_id, bus_number }

// Live arrivals board
let boardStops = [];      // flattened {id, name, route} across all routes

// Demo mode
let demoState = null;
let demoPollTimer = null;

// DOM refs (filled in on DOMContentLoaded)
let fromEl, toEl, predictBtn, noticeEl, countEl, busListEl;
let selectedTagEl, gaugeEl, gaugePctEl, levelEl, detailEl, nextEl, nextEtaEl;
let recommendTextEl, historyTagEl, timeBarsEl, daysEl;
let forecastTagEl, chartEl, patternEl, betterEl, confidenceInfoEl;
let myCoordsEl, mySpeedEl, myMatchWrapEl, trackBtnEl, checkoutBtnEl, rideMsgEl;
let onlineDotEl, onlineTextEl;
let liveMapEl, mapTagEl;
let demoBannerEl, demoBannerTextEl, demoTagEl, demoMessageEl, demoToggleEl;
let demoResetEl, demoMsgEl, demoBusesEl;
let newBusRouteEl, newBusNumberEl, newBusCapacityEl, addBusBtnEl, addBusMsgEl;
let adminTokenEl, fleetListEl, fleetTagEl, fleetMsgEl;
let boardStopEl, boardIncludeEl, boardListEl, boardSummaryEl, boardUpdatedEl;
let crowdSourceEl;
let refreshBtnEl, refreshStampEl, autoRefreshEl;
let pageEls, tabEls;

// ---------------------------------------------------------------------
// Auto-refresh
//
// One loop, not six. Every screen used to grow its own setInterval,
// which meant the Predict page (the one people actually stare at) had
// none at all: its crowd figures were frozen at whatever they were
// when you pressed the button. This drives all of them from a single
// timer that knows which page is visible, stops when the window is
// hidden, and backs off when the backend stops answering.
// ---------------------------------------------------------------------

// How often each page is worth re-fetching. Forecast is hourly/weekly
// aggregate data - it doesn't move on a 15s scale, so it only updates
// when asked.
const REFRESH_MS = {
  predict: 15000,
  prediction: 15000,
  insights: 15000,
  map: 8000,
  board: 10000,
  manage: 20000,
  forecast: 0,
};

// Past this, the numbers on screen are old enough that saying so is
// more useful than showing them at full confidence.
const STALE_AFTER_MS = 45000;
// Past this, an arrival countdown has drifted too far from its last
// real measurement to keep ticking down honestly.
const ETA_TICK_LIMIT_MS = 180000;

let currentPage = "predict";
let autoRefresh = true;
let refreshTimer = null;
let tickTimer = null;
let refreshInFlight = false;
let lastRefreshAt = null;     // ms timestamp of the last successful refresh
let nextRefreshAt = null;     // ms timestamp the loop is aiming for
let refreshFailures = 0;      // consecutive failures, drives the backoff
let backendUp = null;         // null = not yet known

// Crowd-level dropdowns are rebuilt on every render. Without this, an
// auto-refresh landing mid-report would silently reset the user's
// choice back to 3 just before they pressed Submit.
const crowdSelections = new Map(); // bus_id -> selected level

// Set while a dropdown in the bus list has focus. A background refresh
// that rebuilds innerHTML underneath an open <select> closes it and
// loses the tap - so the render waits instead.
let suspendListRender = false;
let listRenderPending = false;

function markBackendUp() {
  const wasDown = backendUp === false;
  backendUp = true;
  refreshFailures = 0;
  if (onlineDotEl) onlineDotEl.classList.remove("offline");
  if (onlineTextEl && wasDown) onlineTextEl.textContent = "Prediction engine online";
}

function markBackendDown(err) {
  backendUp = false;
  if (onlineDotEl) onlineDotEl.classList.add("offline");
  if (onlineTextEl) onlineTextEl.textContent = "Backend unreachable";
  if (err) console.warn("refresh failed:", err);
}

// Exponential backoff, capped. A backend that's down for a coffee break
// shouldn't be getting hit every 8 seconds for the whole break.
function currentInterval() {
  let base = REFRESH_MS[currentPage] || 0;
  if (!base) return 0;

  // Pushes cover crowd changes, so the poll only has to catch what the
  // stream can't tell us about - a bus added to the fleet, a stream
  // that is open but silently dead.
  if (streamConnected) base *= STREAM_POLL_MULTIPLIER;

  if (!refreshFailures) return base;
  return Math.min(base * 2 ** Math.min(refreshFailures, 4), 120000);
}

function setRefreshBusy(busy) {
  if (!refreshBtnEl) return;
  refreshBtnEl.classList.toggle("spinning", busy);
  refreshBtnEl.disabled = busy;
}

// "Updated 12s ago" beats a spinner that has already stopped: it tells
// you how much to trust what you're reading.
function renderRefreshStamp() {
  if (!refreshStampEl) return;

  if (refreshInFlight) {
    refreshStampEl.textContent = "Updating\u2026";
    return;
  }
  if (backendUp === false) {
    const wait = nextRefreshAt ? Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000)) : null;
    refreshStampEl.textContent = wait != null ? `Offline \u00b7 retrying in ${wait}s` : "Offline";
    return;
  }
  if (lastRefreshAt == null) {
    refreshStampEl.textContent = "Not updated yet";
    return;
  }

  const age = Date.now() - lastRefreshAt;
  document.body.classList.toggle("stale", age > STALE_AFTER_MS);

  if (age < 5000) refreshStampEl.textContent = "Updated just now";
  else if (age < 60000) refreshStampEl.textContent = `Updated ${Math.round(age / 1000)}s ago`;
  else {
    const mins = Math.round(age / 60000);
    refreshStampEl.textContent = `Updated ${mins} min ago`;
  }
}

// Which fetches each page actually needs. Refreshing the fleet while
// you're reading the arrivals board is just battery and bandwidth.
async function refreshCurrentPage({ manual = false } = {}) {
  if (refreshInFlight) return;
  if (!manual && document.hidden) return;

  refreshInFlight = true;
  setRefreshBusy(true);
  renderRefreshStamp();

  const jobs = [];

  // Routes are loaded once at startup, but if that failed (app opened
  // a second before uvicorn did, laptop asleep on the bus) there is
  // nothing else in the app that would ever try again.
  if (!routes.length) jobs.push(loadRoutes());

  switch (currentPage) {
    case "predict":
    case "prediction":
    case "insights":
      jobs.push(refreshCandidates(), pollAllBuses());
      break;
    case "map":
      jobs.push(pollAllBuses());
      break;
    case "board":
      jobs.push(loadBoard());
      break;
    case "manage":
      // A half-typed delete confirmation is not worth interrupting for
      // a routine refresh.
      if (pendingDeleteId == null) jobs.push(loadFleet());
      jobs.push(refreshDemo());
      break;
    case "forecast":
      if (manual && selectedBusId != null) {
        const c = candidates.find((x) => x.bus.id === selectedBusId && !x.error);
        if (c) jobs.push(loadForecast(c.bus.id, c.fromStop.id));
      }
      break;
  }

  // The demo banner is global, so its state has to stay current no
  // matter which page you're on.
  if (demoState?.running && currentPage !== "manage") jobs.push(refreshDemo());

  try {
    await Promise.allSettled(jobs);
    if (backendUp !== false) lastRefreshAt = Date.now();
  } finally {
    refreshInFlight = false;
    setRefreshBusy(false);
    scheduleNextRefresh();
    renderRefreshStamp();
  }
}

function scheduleNextRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  nextRefreshAt = null;

  if (!autoRefresh || document.hidden) return;

  const delay = currentInterval();
  if (!delay) return;

  nextRefreshAt = Date.now() + delay;
  // setTimeout rather than setInterval: a slow round-trip can't stack
  // requests on top of each other this way.
  refreshTimer = setTimeout(() => refreshCurrentPage(), delay);
}

function startAutoRefresh({ immediate = false } = {}) {
  if (!tickTimer) tickTimer = setInterval(tick, 1000);
  if (immediate) refreshCurrentPage();
  else scheduleNextRefresh();
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  nextRefreshAt = null;
}

// One second heartbeat. Cheap on purpose: it only rewrites a few text
// nodes, never a whole list, so it can't fight with what you're doing.
function tick() {
  renderRefreshStamp();
  tickLiveEtas();
  tickReportButtons();
}

// Between fetches, an arrival that was "6 min" a minute ago is "5 min"
// now. Counting down from a measured figure is honest; inventing one is
// not - so this only touches estimates the backend actually gave a
// number for, and gives up once the reading is too old to trust.
function liveEtaText(el) {
  const status = el.dataset.etaStatus;
  const at = Number(el.dataset.etaAt);
  if (!at || Date.now() - at > ETA_TICK_LIMIT_MS) return null;

  const elapsed = (Date.now() - at) / 1000;

  if (status === "approaching") {
    const secs = Number(el.dataset.etaSecs);
    if (!Number.isFinite(secs)) return null;
    const left = secs - elapsed;
    if (left < 45) return "Arriving";
    return `${Math.round(left / 60)} min`;
  }

  if (status === "uncertain") {
    const lo = Number(el.dataset.etaSecs);
    const hi = Number(el.dataset.etaMax);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
    const loLeft = Math.max(0, lo - elapsed);
    const hiLeft = Math.max(0, hi - elapsed);
    if (hiLeft < 45) return "Arriving";
    return `${Math.round(loLeft / 60)}\u2013${Math.round(hiLeft / 60)} min`;
  }

  return null;
}

function tickLiveEtas() {
  document.querySelectorAll(".eta-main[data-eta-at]").forEach((el) => {
    const text = liveEtaText(el);
    if (text && el.textContent !== text) el.textContent = text;
  });
}

// The report cooldown used to only update when something else forced a
// re-render, so the button could sit on "Update in 41s" long after it
// was ready.
function tickReportButtons() {
  if (!busListEl) return;
  busListEl.querySelectorAll("[data-report]").forEach((btn) => {
    const busId = Number(btn.dataset.report);
    const left = cooldownRemaining(busId);
    const text = left > 0
      ? `Update in ${left}s`
      : reportCooldowns.has(busId)
      ? "Update my report"
      : "Submit crowd report";
    if (btn.textContent.trim() !== text) btn.textContent = text;
  });
}

function setAutoRefresh(on) {
  autoRefresh = on;
  if (autoRefreshEl) autoRefreshEl.checked = on;
  if (on) startAutoRefresh({ immediate: true });
  else stopAutoRefresh();
  renderRefreshStamp();
}

// ---------------------------------------------------------------------
// Live stream
//
// Polling is us guessing how often something might have changed. The
// stream is the server telling us. EventSource is used directly rather
// than proxied through Rust because it already implements reconnection
// and backoff correctly, and reimplementing both badly is how a
// dropped connection becomes a reconnect storm.
//
// The polling loop above is kept as the fallback and simply slows down
// while the stream is up, so losing the stream degrades to the
// previous behaviour instead of to a frozen screen.
// ---------------------------------------------------------------------
let eventSource = null;
let streamConnected = false;

// While connected, poll this much less often. Not zero: the stream
// carries crowd changes, but nothing pushes a *new* bus into a search
// or notices a fleet edit, and a slow poll is a cheap backstop against
// a stream that is open but silently dead.
const STREAM_POLL_MULTIPLIER = 4;

async function connectStream() {
  if (eventSource) return;

  let base;

  try {
    base = await invoke("get_api_base_url");
  } catch {
    return; // Older shell without the command; polling carries on.
  }

  try {
    eventSource = new EventSource(`${base}/api/stream`);
  } catch {
    return;
  }

  eventSource.addEventListener("connected", () => {
    streamConnected = true;
    renderStreamState();
    // Re-time the loop to its slower cadence now that pushes arrive.
    stopAutoRefresh();
    scheduleNextRefresh();
  });

  eventSource.addEventListener("bus_status", (event) => {
    try {
      applyStreamedStatus(JSON.parse(event.data).data);
    } catch {
      // A malformed frame is not worth tearing the stream down for.
    }
  });

  eventSource.addEventListener("fleet_changed", () => {
    if (currentPage === "manage") loadFleet();
  });

  eventSource.addEventListener("demo_changed", () => refreshDemo());

  eventSource.onerror = () => {
    // EventSource reconnects on its own; all we do is stop claiming
    // to be live, which speeds the polling loop back up.
    streamConnected = false;
    renderStreamState();
    scheduleNextRefresh();
  };
}

// A pushed figure is a partial update: crowd numbers change, the
// arrival estimate doesn't come with it. Patching only what arrived
// keeps the row honest rather than blanking the fields the frame
// didn't mention.
function applyStreamedStatus(data) {
  if (!data || data.bus_id == null) return;

  const c = candidates.find((x) => x.bus.id === data.bus_id);

  if (!c || !c.status) return;

  c.status.overall_fullness = data.overall_fullness ?? c.status.overall_fullness;
  c.status.crowd_source = data.crowd_source ?? c.status.crowd_source;
  c.status.trend = data.trend ?? c.status.trend;
  c.status.active_passengers = data.active_passengers ?? c.status.active_passengers;
  c.status.reporter_count = data.reporter_count ?? c.status.reporter_count;

  lastRefreshAt = Date.now();

  renderList();
  if (selectedBusId === data.bus_id) renderSelected();
}

function renderStreamState() {
  if (!onlineTextEl) return;
  if (backendUp === false) return;

  onlineTextEl.textContent = streamConnected
    ? "Live \u00b7 updates pushed"
    : "Prediction engine online";
}

// ---------------------------------------------------------------------
// Arrival alarms
//
// The feature people would actually use daily: tell me when this bus
// is close, so I can stop watching the screen. Held in memory and in
// the snapshot below, checked against every data update rather than on
// their own timer - the alarm is a view of the ETA, not a second
// source of truth about it.
// ---------------------------------------------------------------------
const alarms = new Map();   // bus_id -> { stopId, minutes, bus_number, fired }

function setAlarm(busId, minutes) {
  const c = candidates.find((x) => x.bus.id === busId);
  if (!c) return;

  alarms.set(busId, {
    stopId: c.fromStop.id,
    stopName: c.fromStop.name,
    minutes,
    busNumber: c.bus.bus_number,
    fired: false,
  });

  persistAlarms();
  renderList();
}

function clearAlarm(busId) {
  alarms.delete(busId);
  persistAlarms();
  renderList();
}

function checkArrivalAlarms() {
  for (const [busId, alarm] of alarms) {
    const c = candidates.find((x) => x.bus.id === busId);

    if (!c || !c.eta || c.eta.eta_seconds == null) continue;
    if (c.eta.status !== "approaching" && c.eta.status !== "uncertain") continue;

    const minutesAway = c.eta.eta_seconds / 60;

    if (minutesAway > alarm.minutes) {
      // Moved back out of range - re-arm, so a bus stuck in traffic
      // that drifts either side of the threshold can alert again once
      // it's genuinely close.
      alarm.fired = false;
      continue;
    }

    if (alarm.fired) continue;

    alarm.fired = true;
    persistAlarms();

    invoke("send_user_notification", {
      title: `${alarm.busNumber} is nearly at ${alarm.stopName}`,
      body:
        minutesAway < 1
          ? "Arriving now."
          : `About ${Math.round(minutesAway)} min away.`,
    }).catch(() => {
      // Permission denied. The row still shows the armed alarm, so
      // the information isn't lost - just not pushed.
    });
  }
}

// ---------------------------------------------------------------------
// Offline snapshot
//
// A phone in a dead-signal area between stops shouldn't show a blank
// screen. This keeps the last known good state so the app opens with
// something, clearly marked as old rather than presented as current.
// ---------------------------------------------------------------------
const CACHE_KEY = "BusMitra:snapshot:v1";
const ALARM_KEY = "BusMitra:alarms:v1";

// Past this, cached figures are archaeology and showing them would be
// worse than showing nothing.
const CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000;

function cacheSnapshot() {
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        at: Date.now(),
        from: fromEl?.value ?? null,
        to: toEl?.value ?? null,
        // Only what's needed to redraw the list. Routes are re-fetched
        // on connect, so caching them too would just create a second
        // copy to keep in sync.
        candidates: candidates.map((c) => ({
          busId: c.bus.id,
          busNumber: c.bus.bus_number,
          routeNumber: c.route.route_number,
          fromStopName: c.fromStop.name,
          fullness: c.prediction?.final_fullness ?? null,
          status: c.prediction?.status ?? null,
          etaSeconds: c.eta?.eta_seconds ?? null,
        })),
      })
    );
  } catch {
    // Storage full or disabled. The cache is a nicety.
  }
}

function renderCachedSnapshot() {
  let snapshot;

  try {
    snapshot = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
  } catch {
    return false;
  }

  if (!snapshot || !snapshot.candidates?.length) return false;

  const age = Date.now() - snapshot.at;

  if (age > CACHE_MAX_AGE_MS) return false;

  const when = new Date(snapshot.at).toLocaleTimeString();

  busListEl.innerHTML =
    `<div class="notice show">Showing the last numbers this app saw, from ${esc(when)}. ` +
    `They are not live.</div>` +
    snapshot.candidates
      .map(
        (c) => `<div class="bus" style="opacity:.6">
          <div class="bus-head">
            <div class="route"><div class="number">${esc(c.routeNumber)}</div>
              <div class="route-name">${esc(c.busNumber)}</div></div>
            <div class="eta muted"><b class="eta-main">${
              c.etaSeconds != null ? Math.round(c.etaSeconds / 60) + " min" : "\u2014"
            }</b><span>${esc(c.fromStopName)} &middot; cached</span></div>
          </div>
          <div class="bus-meta"><div class="status">${
            c.fullness != null ? Math.round(c.fullness) + "% full" : "Unknown"
          }</div></div>
        </div>`
      )
      .join("");

  return true;
}

function persistAlarms() {
  try {
    localStorage.setItem(ALARM_KEY, JSON.stringify([...alarms.entries()]));
  } catch {
    // Non-fatal.
  }
}

function restoreAlarms() {
  try {
    const saved = JSON.parse(localStorage.getItem(ALARM_KEY) || "[]");
    for (const [busId, alarm] of saved) alarms.set(Number(busId), alarm);
  } catch {
    // Non-fatal.
  }
}

// ---------------------------------------------------------------------
// Page navigation (bottom tab bar). Only one <section class="page"> is
// visible at a time so each screen fits with minimal scrolling.
// ---------------------------------------------------------------------
function showPage(name) {
  pageEls.forEach((el) => el.classList.toggle("active", el.dataset.page === name));
  tabEls.forEach((el) => el.classList.toggle("active", el.dataset.page === name));
  // The map is only ever measured correctly once its container is
  // actually visible, so re-measure it right after we reveal it.
  if (name === "map" && map) setTimeout(() => map.invalidateSize(), 0);

  currentPage = name;

  // Arriving on a screen is exactly when its numbers matter most, so
  // fetch immediately rather than waiting out the interval. The loop
  // then re-times itself to whatever cadence this page wants.
  stopAutoRefresh();
  refreshCurrentPage({ manual: true });
}

function setupNavigation() {
  pageEls = [...document.querySelectorAll(".page")];
  tabEls = [...document.querySelectorAll(".tab")];
  tabEls.forEach((tab) => {
    tab.addEventListener("click", () => showPage(tab.dataset.page));
  });
}

// ---------------------------------------------------------------------
// Live map (Leaflet, dark tiles to match the app theme)
// ---------------------------------------------------------------------
let map = null;
let userMarker = null;
const busMarkers = new Map(); // bus_id -> L.marker
const userIcon = () =>
  L.divIcon({ className: "user-marker", html: '<div class="user-dot"></div>', iconSize: [16, 16] });
const busIcon = () =>
  L.divIcon({ className: "bus-marker", html: '<div class="bus-dot">\u{1F68C}</div>', iconSize: [26, 26] });

function initMap() {
  if (!liveMapEl || typeof L === "undefined") return;
  map = L.map(liveMapEl, { zoomControl: true }).setView([20, 0], 2);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);

  // Leaflet mis-measures its container if the map is created while the
  // layout is still settling (webfonts loading, sidebar animating in,
  // etc). Re-measure a couple of times after startup, on every window
  // resize, and whenever the tab/window regains visibility, so the tile
  // grid never gets stuck showing a stale/blank size.
  setTimeout(() => map.invalidateSize(), 300);
  setTimeout(() => map.invalidateSize(), 1000);
  window.addEventListener("resize", () => map.invalidateSize());
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) map.invalidateSize();
  });
}

function fitMapToStops() {
  if (!map) return;
  const pts = [];
  for (const route of routes) {
    for (const stop of route.stops) pts.push([stop.latitude, stop.longitude]);
  }
  if (pts.length) map.fitBounds(pts, { padding: [30, 30] });
}

function updateUserMarker(lat, lon) {
  if (!map) return;
  if (!userMarker) {
    userMarker = L.marker([lat, lon], { icon: userIcon(), zIndexOffset: 1000 }).addTo(map).bindPopup("You are here");
    map.setView([lat, lon], 15);
    if (mapTagEl) mapTagEl.textContent = "Tracking your location";
  } else {
    userMarker.setLatLng([lat, lon]);
  }
}

function updateBusMarker(status) {
  if (!map || !status || status.latest_latitude == null || status.latest_longitude == null) return;
  const pos = [status.latest_latitude, status.latest_longitude];
  let marker = busMarkers.get(status.bus_id);
  if (!marker) {
    marker = L.marker(pos, { icon: busIcon() }).addTo(map);
    busMarkers.set(status.bus_id, marker);
  } else {
    marker.setLatLng(pos);
  }
  marker.setPopupContent(`<b>${esc(status.bus_number)}</b><br>${Math.round(status.overall_fullness)}% full`);
  if (!marker.getPopup()) marker.bindPopup(`<b>${esc(status.bus_number)}</b><br>${Math.round(status.overall_fullness)}% full`);
}

// A deleted bus keeps its marker until something removes it, which
// would leave a ghost sitting on the map for the rest of the session.
function dropBusMarker(busId) {
  const marker = busMarkers.get(busId);
  if (!marker) return;
  if (map) map.removeLayer(marker);
  busMarkers.delete(busId);
}

// Keep every bus on the map moving, not just the ones from the last
// search. Polls all known bus ids on a fixed interval for as long as
// the app is open.
async function pollAllBuses() {
  const busIds = new Set();
  for (const route of routes) {
    for (const bus of route.buses) busIds.add(bus.id);
  }
  if (!busIds.size) return;

  let ok = 0;
  let failed = 0;
  await Promise.all(
    [...busIds].map(async (busId) => {
      try {
        const status = await invoke("get_bus_status", { busId });
        updateBusMarker(status);
        ok++;
      } catch {
        // A single bus failing to report shouldn't stop the others.
        failed++;
      }
    })
  );

  // One bus erroring is a bus problem. Every bus erroring is a backend
  // problem, and the status light should say so.
  if (ok > 0) markBackendUp();
  else if (failed > 0) {
    refreshFailures++;
    markBackendDown();
  }
}

// ---------------------------------------------------------------------
// Small geo helper (mirrors backend/app/services/bus_matching.py)
// ---------------------------------------------------------------------
function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}
function formatDistance(meters) {
  if (meters == null) return null;
  if (meters < 1000) return `${Math.round(meters)} m away`;
  return `${(meters / 1000).toFixed(1)} km away`;
}

// ---------------------------------------------------------------------
// Arrival display
//
// The estimate itself now comes from the backend, which measures
// progress along the route's own polyline rather than crow-flies
// distance over instantaneous speed. That means it can also answer
// "already passed you", "not moving" and "don't know yet" - so the
// job here is only to render whichever of those came back, never to
// invent a number when one is missing.
// ---------------------------------------------------------------------
const ETA_STATUS_LABEL = {
  heading_away: "Already passed",
  stopped: "Not moving",
  no_data: "No live position",
  off_route: "Off route",
  uncertain: "Uncertain",
};

function etaHeadline(eta) {
  if (!eta) return "No estimate";
  if (eta.status === "approaching") {
    if (eta.eta_seconds < 45) return "Arriving";
    return `${Math.round(eta.eta_minutes)} min`;
  }
  if (eta.status === "uncertain" && eta.eta_seconds != null) {
    return `${Math.round(eta.eta_seconds / 60)}\u2013${Math.round(eta.eta_max_seconds / 60)} min`;
  }
  return ETA_STATUS_LABEL[eta.status] || "No estimate";
}

function etaDetail(eta) {
  if (!eta) return "";
  const bits = [];
  if (eta.distance_meters != null) {
    bits.push(
      eta.distance_meters < 1000
        ? `${Math.round(eta.distance_meters)} m along route`
        : `${(eta.distance_meters / 1000).toFixed(1)} km along route`
    );
  }
  if (eta.stops_away != null && eta.stops_away > 0) {
    bits.push(`${eta.stops_away} stop${eta.stops_away === 1 ? "" : "s"} away`);
  }
  if (eta.speed_kmh != null && eta.speed_kmh > 0) {
    bits.push(`${Math.round(eta.speed_kmh)} km/h`);
  }
  return bits.join(" \u00b7 ");
}

function etaClass(eta) {
  if (!eta) return "muted";
  if (eta.status === "approaching") return eta.confidence === "high" ? "good" : "ok";
  if (eta.status === "uncertain") return "ok";
  return "muted";
}

// Describes where a crowd figure came from, so the number isn't
// presented as if every source were equally certain.
function crowdSourceLabel(status) {
  if (!status) return "\u2014";
  const riders = `${status.active_passengers} phone${status.active_passengers === 1 ? "" : "s"}`;
  const reports = `${status.reporter_count} report${status.reporter_count === 1 ? "" : "s"}`;
  if (status.crowd_source === "blended") return `${riders} + ${reports}`;
  if (status.crowd_source === "reports") return `${reports} from riders`;
  if (status.crowd_source === "devices") return riders;
  return "No live signal";
}

const TREND_LABEL = { rising: "\u2191 filling up", falling: "\u2193 emptying", steady: "\u2192 steady" };

// ---------------------------------------------------------------------
// Legacy straight-line helper, kept only for the map distance readout.
// Not used for arrival times: see the note above.
// stop (haversine, above) and its latest reported ground speed
// (BusStatusResponse.latest_speed, km/h, from the matched rider's GPS
// ping). No made-up numbers: if we don't have both a live distance and
// a live, moving speed reading, we say so instead of guessing.
// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
// Backend data loading
// ---------------------------------------------------------------------
async function loadRoutes() {
  try {
    routes = await invoke("get_routes");
    markBackendUp();
    onlineTextEl.textContent = "Prediction engine online";
    populateStopSelects();
    populateRouteSelect();
    populateBoardStops();
    fitMapToStops();
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    busListEl.innerHTML = `<div class="empty">Can't reach the backend (${esc(err)}). Check that uvicorn is running, then press the refresh button up top.</div>`;
  }
}

function populateStopSelects() {
  const seen = new Set();
  const names = [];
  for (const route of routes) {
    for (const stop of route.stops) {
      if (!seen.has(stop.name)) {
        seen.add(stop.name);
        names.push(stop.name);
      }
    }
  }
  // Adding or deleting a bus reloads the routes, and rebuilding these
  // selects from scratch would silently throw away whatever journey
  // the user had picked. Put it back when the stops still exist.
  const previousFrom = fromEl.value;
  const previousTo = toEl.value;

  const optionsHtml = names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
  fromEl.innerHTML = optionsHtml;
  toEl.innerHTML = optionsHtml;

  if (names.includes(previousFrom)) fromEl.value = previousFrom;
  else if (names.length) fromEl.value = names[0];

  if (names.includes(previousTo) && previousTo !== fromEl.value) toEl.value = previousTo;
  else if (names.length > 1) toEl.value = names.find((n) => n !== fromEl.value) ?? names[1];
}

function populateRouteSelect() {
  if (!newBusRouteEl) return;
  const previous = newBusRouteEl.value;
  newBusRouteEl.innerHTML = routes
    .map((r) => `<option value="${r.route_id}">${esc(r.route_number)} — ${esc(r.route_name)}</option>`)
    .join("");
  if (previous && routes.some((r) => String(r.route_id) === previous)) {
    newBusRouteEl.value = previous;
  }
}

// ---------------------------------------------------------------------
// Journey search -> candidate buses
// ---------------------------------------------------------------------
function findCandidates(fromName, toName) {
  const found = [];
  for (const route of routes) {
    const idxFrom = route.stops.findIndex((s) => s.name === fromName);
    const idxTo = route.stops.findIndex((s) => s.name === toName);
    if (idxFrom === -1 || idxTo === -1 || idxFrom >= idxTo) continue;

    const fromStop = route.stops[idxFrom];
    const toStop = route.stops[idxTo];
    const primaryBusId = Math.min(...route.buses.map((b) => b.id));

    for (const bus of route.buses) {
      found.push({
        bus,
        route,
        fromStop,
        toStop,
        isPrimary: bus.id === primaryBusId,
      });
    }
  }
  return found;
}

// ---------------------------------------------------------------------
// Fetching bus state
//
// One request for the whole list instead of three per bus. Five buses
// used to mean fifteen round trips, repeated on every refresh; it also
// meant the crowd figure and the arrival time on one row could come
// from moments seconds apart, because they were separate calls.
//
// Candidates are grouped by boarding stop, since the batch endpoint
// measures arrivals against one stop at a time. In practice a search
// produces one or two groups.
// ---------------------------------------------------------------------
let batchSupported = true;

async function fetchBusStates(candidates) {
  if (batchSupported) {
    try {
      return await fetchBusStatesBatched(candidates);
    } catch (err) {
      // An older backend without /api/buses/status. Fall back for the
      // rest of the session rather than failing this refresh and every
      // one after it.
      if (/404|not found|unexpected/i.test(String(err))) {
        batchSupported = false;
      } else {
        throw err;
      }
    }
  }

  return fetchBusStatesIndividually(candidates);
}

async function fetchBusStatesBatched(candidates) {
  const byStop = new Map();
  for (const c of candidates) {
    if (!byStop.has(c.fromStop.id)) byStop.set(c.fromStop.id, []);
    byStop.get(c.fromStop.id).push(c);
  }

  const out = [];

  await Promise.all(
    [...byStop.entries()].map(async ([stopId, group]) => {
      const response = await invoke("get_batch_status", {
        busIds: group.map((c) => c.bus.id),
        stopId,
      });

      const byId = new Map(response.buses.map((b) => [b.bus_id, b]));

      for (const c of group) {
        const state = byId.get(c.bus.id);

        if (!state) {
          // Deleted between the last route load and now. The backend
          // reports these rather than failing the batch.
          out.push({ ...c, error: "This bus is no longer in the fleet.", fetchedAt: Date.now() });
          continue;
        }

        out.push({ ...c, ...unpackBusState(c, state) });
      }
    })
  );

  return out;
}

// The batch response nests eta and prediction; the rest of the app
// expects them as siblings of status, so this is the one place that
// knows about the difference.
function unpackBusState(c, state) {
  const status = {
    bus_id: state.bus_id,
    bus_number: state.bus_number,
    route_id: state.route_id,
    latest_latitude: state.latest_latitude,
    latest_longitude: state.latest_longitude,
    latest_speed: state.latest_speed,
    latest_timestamp: state.latest_timestamp,
    active_passengers: state.active_passengers,
    passenger_fullness: state.passenger_fullness,
    manual_fullness: state.manual_fullness,
    overall_fullness: state.overall_fullness,
    report_count: state.report_count,
    reporter_count: state.reporter_count,
    passenger_weight: state.passenger_weight,
    report_weight: state.report_weight,
    crowd_source: state.crowd_source,
    trend: state.trend,
  };

  let distance = null;

  if (status.latest_latitude != null && status.latest_longitude != null) {
    distance = haversineMeters(
      status.latest_latitude,
      status.latest_longitude,
      c.fromStop.latitude,
      c.fromStop.longitude
    );
    updateBusMarker(status);
  }

  return {
    status,
    prediction: state.prediction,
    eta: state.eta,
    distance,
    error: null,
    fetchedAt: Date.now(),
  };
}

async function fetchBusStatesIndividually(candidates) {
  return Promise.all(
    candidates.map(async (c) => {
      try {
        const [status, prediction, eta] = await Promise.all([
          invoke("get_bus_status", { busId: c.bus.id }),
          invoke("get_bus_prediction", { busId: c.bus.id, stopId: c.fromStop.id }),
          invoke("get_bus_eta", { busId: c.bus.id, stopId: c.fromStop.id }),
        ]);

        let distance = null;

        if (status.latest_latitude != null && status.latest_longitude != null) {
          distance = haversineMeters(
            status.latest_latitude,
            status.latest_longitude,
            c.fromStop.latitude,
            c.fromStop.longitude
          );
          updateBusMarker(status);
        }

        return { ...c, status, prediction, eta, distance, error: null, fetchedAt: Date.now() };
      } catch (err) {
        return {
          ...c, status: null, prediction: null, eta: null,
          distance: null, error: String(err), fetchedAt: Date.now(),
        };
      }
    })
  );
}

async function runPredict() {
  const fromName = fromEl.value;
  const toName = toEl.value;
  selectedBusId = null;

  const found = findCandidates(fromName, toName);

  if (found.length === 0) {
    noticeEl.textContent = "No direct bus was found between these locations. Try reversing them or picking a different pair of stops.";
    noticeEl.classList.remove("good");
    noticeEl.classList.add("show");
    candidates = [];
    countEl.textContent = "0";
    busListEl.innerHTML = '<div class="empty">No direct buses found for this journey.<br>Try reversing the locations or choosing another pair of stops.</div>';
    renderSelected();
    return;
  }

  predictBtn.disabled = true;
  predictBtn.textContent = "Loading\u2026";

  const results = await fetchBusStates(found);

  // Soonest arrival first. Sorting by straight-line distance used to
  // put a bus that had already passed the stop at the top of the list
  // purely because it was still nearby.
  results.sort((a, b) => {
    const ea = a.eta?.eta_seconds ?? null;
    const eb = b.eta?.eta_seconds ?? null;
    if (ea == null && eb == null) return 0;
    if (ea == null) return 1;
    if (eb == null) return -1;
    return ea - eb;
  });

  candidates = results;
  // Any background refresh still in flight was fetching the previous
  // journey's buses; bumping the generation makes its results a no-op.
  candidateRefreshGeneration++;
  selectedBusId = candidates.find((c) => !c.error)?.bus.id ?? null;
  lastRefreshAt = Date.now();

  const okCount = candidates.filter((c) => !c.error).length;
  noticeEl.classList.remove("show");
  if (okCount > 0) {
    const best = candidates.find((c) => !c.error);
    noticeEl.textContent = `${okCount} direct bus${okCount > 1 ? "es" : ""} found. Lowest predicted crowd: ${best.bus.bus_number} at ${Math.round(best.prediction.final_fullness)}%.`;
    noticeEl.classList.add("good", "show");
  }

  predictBtn.disabled = false;
  predictBtn.textContent = "Predict buses \u2192";

  checkArrivalAlarms();
  cacheSnapshot();

  renderList();
  renderSelected();
}

// Re-fetch the numbers for buses already on screen, without disturbing
// the user's search. Used after demo mode starts or stops, since every
// figure on the Predict page changes at that moment.
let candidateRefreshGeneration = 0;

async function refreshCandidates() {
  if (!candidates.length) return;

  // A slow round-trip must never overwrite a newer one. Without this,
  // pressing Predict while a background refresh is in flight can land
  // the old journey's numbers on the new journey's list.
  const generation = ++candidateRefreshGeneration;

  let fresh;

  try {
    fresh = await fetchBusStates(candidates);
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    return;
  }

  // Superseded by a newer search or refresh - its render already ran.
  if (generation !== candidateRefreshGeneration) return;

  const failed = fresh.filter((c) => c.error).length;

  if (failed === fresh.length && failed > 0) {
    refreshFailures++;
    markBackendDown();
  } else {
    markBackendUp();
  }

  // Updated in place rather than replaced, so selection and ordering
  // survive - re-sorting a list someone is reading is hostile, and
  // rebuilding the array would drop selectedBusId's target.
  const byId = new Map(fresh.map((c) => [c.bus.id, c]));

  for (const c of candidates) {
    const updated = byId.get(c.bus.id);
    if (!updated) continue;

    c.status = updated.status;
    c.prediction = updated.prediction;
    c.eta = updated.eta;
    c.distance = updated.distance;
    c.error = updated.error;
    c.fetchedAt = updated.fetchedAt;
  }

  checkArrivalAlarms();
  cacheSnapshot();

  renderList();
  renderSelected();
}

// ---------------------------------------------------------------------
// Rendering: bus list
// ---------------------------------------------------------------------
function renderList() {
  countEl.textContent = candidates.filter((c) => !c.error).length;

  if (candidates.length === 0) return;

  if (suspendListRender) {
    listRenderPending = true;
    return;
  }

  busListEl.innerHTML = candidates
    .map((c) => {
      const open = selectedBusId === c.bus.id;
      if (c.error) {
        return `<div class="bus" data-id="${c.bus.id}">
          <div class="bus-head"><div class="route"><div class="number">${esc(c.route.route_number)}</div><div class="route-name">${esc(c.bus.bus_number)}</div></div></div>
          <div class="bus-meta"><span style="color:var(--red);font-size:11px">Couldn't load this bus (${esc(c.error)})</span></div>
        </div>`;
      }
      const pct = Math.round(c.prediction.final_fullness);
      const color = colorFor(c.prediction.status);
      const etaMain = etaHeadline(c.eta);
      const detail = etaDetail(c.eta);
      const etaSub = detail
        ? `${detail} \u00b7 ${esc(c.fromStop.name)}`
        : esc(c.fromStop.name);
      // The countdown keeps running between fetches, so the headline
      // carries the measurement it was derived from and when it was
      // taken. tickLiveEtas() reads these back once a second.
      const etaAttrs = c.eta
        ? ` data-eta-at="${c.fetchedAt ?? Date.now()}" data-eta-status="${esc(c.eta.status)}"` +
          (c.eta.eta_seconds != null ? ` data-eta-secs="${c.eta.eta_seconds}"` : "") +
          (c.eta.eta_max_seconds != null ? ` data-eta-max="${c.eta.eta_max_seconds}"` : "")
        : "";
      const primaryBus = c.route.buses.find((b) => b.id === Math.min(...c.route.buses.map((x) => x.id)));
      const liveTag = c.isPrimary
        ? `<span class="factor">Live GPS matched</span>`
        : `<span class="no-live-tag">Prediction only (this route's live GPS goes to ${esc(primaryBus.bus_number)})</span>`;

      // One button, two meanings: you can only be on one bus, so the
      // bus you're riding offers Check out and every other bus offers
      // Check in.
      const riding = currentRide != null && currentRide.bus_id === c.bus.id;
      const rideButton = riding
        ? `<button class="action-btn danger" data-checkout="${c.bus.id}">Check out of this bus</button>`
        : `<button class="action-btn" data-checkin="${c.bus.id}">Check in to this bus</button>`;

      return `<div class="bus ${open ? "selected" : ""} ${riding ? "riding" : ""}" data-id="${c.bus.id}">
        <div class="bus-head">
          <div class="route"><div class="number">${esc(c.route.route_number)}</div><div class="route-name">${esc(c.bus.bus_number)}</div></div>
          <div class="eta ${etaClass(c.eta)}"><b class="eta-main"${etaAttrs}>${etaMain}</b><span>${etaSub}</span></div>
        </div>
        <div class="bus-meta">
          <div class="mini-bar"><div class="fill" style="width:${Math.min(100, pct)}%;background:${color}"></div></div>
          <div class="status" style="color:${color}">${esc(c.prediction.status)}</div>
          <div class="confidence">${esc(crowdSourceLabel(c.status))}${c.status.trend && c.status.trend !== "unknown" ? ` &middot; ${TREND_LABEL[c.status.trend]}` : ""}</div>
        </div>
        <div class="expand">
          <div class="factors">${liveTag}<span class="factor">${esc(c.route.route_name)}</span></div>
          <div class="bus-actions">
            ${rideButton}
            <button class="action-btn secondary" data-view-prediction="${c.bus.id}">View full prediction &rarr;</button>
          </div>
          <div class="bus-actions">
            ${
              alarms.has(c.bus.id)
                ? `<button class="action-btn danger" data-alarm-off="${c.bus.id}">Cancel ${alarms.get(c.bus.id).minutes}-min alert</button>`
                : `<button class="action-btn" data-alarm-on="${c.bus.id}">Alert me 5 min before</button>`
            }
          </div>
          <div class="report-row">
            <select data-crowd-select="${c.bus.id}">
              ${[
                [1, "1 - Very low"], [2, "2 - Low"], [3, "3 - Moderate"],
                [4, "4 - High"], [5, "5 - Very high"],
              ]
                .map(([v, label]) =>
                  `<option value="${v}"${(crowdSelections.get(c.bus.id) ?? 3) === v ? " selected" : ""}>${label}</option>`
                )
                .join("")}
            </select>
            <button class="action-btn" data-report="${c.bus.id}">${
              cooldownRemaining(c.bus.id) > 0
                ? `Update in ${cooldownRemaining(c.bus.id)}s`
                : reportCooldowns.has(c.bus.id)
                ? "Update my report"
                : "Submit crowd report"
            }</button>
          </div>
          <div class="action-msg" id="action-msg-${c.bus.id}"></div>
        </div>
      </div>`;
    })
    .join("");

  busListEl.querySelectorAll(".bus").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".bus-actions") || e.target.closest(".report-row")) return;
      selectedBusId = Number(el.dataset.id);
      renderList();
      renderSelected();
    });
  });
  busListEl.querySelectorAll("[data-checkin]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      doCheckIn(Number(btn.dataset.checkin));
    });
  });
  busListEl.querySelectorAll("[data-checkout]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      doCheckOut(Number(btn.dataset.checkout));
    });
  });
  busListEl.querySelectorAll("[data-alarm-on]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      setAlarm(Number(btn.dataset.alarmOn), 5);
    });
  });
  busListEl.querySelectorAll("[data-alarm-off]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      clearAlarm(Number(btn.dataset.alarmOff));
    });
  });
  busListEl.querySelectorAll("[data-crowd-select]").forEach((sel) => {
    sel.addEventListener("change", () => {
      crowdSelections.set(Number(sel.dataset.crowdSelect), Number(sel.value));
    });
    // Rebuilding the list under an open dropdown is the one thing a
    // background refresh must never do.
    sel.addEventListener("focus", () => (suspendListRender = true));
    sel.addEventListener("blur", () => {
      suspendListRender = false;
      if (listRenderPending) {
        listRenderPending = false;
        // Deferred so the element isn't torn out from under its own
        // blur handler.
        setTimeout(() => {
          renderList();
          renderSelected();
        }, 0);
      }
    });
  });
  busListEl.querySelectorAll("[data-report]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const busId = Number(btn.dataset.report);
      const select = busListEl.querySelector(`[data-crowd-select="${busId}"]`);
      doReport(busId, Number(select.value));
    });
  });
  busListEl.querySelectorAll("[data-view-prediction]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      selectedBusId = Number(btn.dataset.viewPrediction);
      renderList();
      renderSelected();
      showPage("prediction");
    });
  });
}

// ---------------------------------------------------------------------
// Check in / check out
// ---------------------------------------------------------------------
function setRideMessage(text, busId) {
  if (busId != null) {
    const msgEl = document.getElementById(`action-msg-${busId}`);
    if (msgEl) msgEl.textContent = text;
  }
  if (rideMsgEl) rideMsgEl.textContent = text;
}

// The Map page's check-out button only makes sense while a ride is
// open, so it follows currentRide rather than being always visible.
function renderRideControls() {
  if (!checkoutBtnEl) return;
  if (currentRide) {
    checkoutBtnEl.hidden = false;
    checkoutBtnEl.textContent = `Check out of ${currentRide.bus_number}`;
    checkoutBtnEl.disabled = false;
  } else {
    checkoutBtnEl.hidden = true;
  }
}

async function refreshBusNumbers(busId) {
  const c = candidates.find((x) => x.bus.id === busId);
  if (!c) return;
  try {
    const [status, prediction, eta] = await Promise.all([
      invoke("get_bus_status", { busId }),
      invoke("get_bus_prediction", { busId, stopId: c.fromStop.id }),
      invoke("get_bus_eta", { busId, stopId: c.fromStop.id }),
    ]);
    c.status = status;
    c.prediction = prediction;
    c.eta = eta;
    c.fetchedAt = Date.now();
    lastRefreshAt = Date.now();
    renderList();
    if (selectedBusId === busId) renderSelected();
  } catch {
    // The check-in itself already succeeded; a failed refresh just
    // means the list shows slightly stale numbers until next poll.
  }
}

async function doCheckIn(busId) {
  try {
    const res = await invoke("checkin_to_bus", { busId });
    currentRide = { bus_id: res.bus_id, bus_number: res.bus_number };
    renderRideControls();
    setRideMessage(res.message, busId);
    await refreshBusNumbers(busId);
  } catch (err) {
    setRideMessage(`Check-in failed: ${err}`, busId);
  }
}

async function doCheckOut(busId) {
  try {
    // busId is optional server-side: omitting it closes whichever ride
    // is open, which is what the Map page button needs when the ride
    // was started by GPS matching rather than a tap.
    const res = await invoke("checkout_from_bus", { busId: busId ?? null });
    const leftBusId = res.bus_id;
    currentRide = null;
    renderRideControls();
    setRideMessage(res.message, leftBusId);
    await refreshBusNumbers(leftBusId);
  } catch (err) {
    // A 404 means the backend has no open ride for us - our local idea
    // of the ride was stale, so drop it rather than leaving a button
    // that can only ever fail.
    currentRide = null;
    renderRideControls();
    setRideMessage(`Check-out failed: ${err}`, busId);
  }
}

// Buses this device has reported recently, so the button can show the
// cooldown instead of letting someone tap into a 429.
const reportCooldowns = new Map(); // bus_id -> timestamp when allowed again

function cooldownRemaining(busId) {
  const until = reportCooldowns.get(busId);
  if (!until) return 0;
  return Math.max(0, Math.ceil((until - Date.now()) / 1000));
}

async function doReport(busId, crowdLevel) {
  const msgEl = document.getElementById(`action-msg-${busId}`);
  const btn = busListEl.querySelector(`[data-report="${busId}"]`);

  const waiting = cooldownRemaining(busId);
  if (waiting > 0) {
    if (msgEl) msgEl.textContent = `You can update your report in ${waiting}s.`;
    return;
  }

  if (btn) btn.disabled = true;

  try {
    const res = await invoke("submit_crowd_report", { busId, crowdLevel });

    reportCooldowns.set(
      busId,
      Date.now() + (res.next_report_in_seconds || 60) * 1000
    );

    // The backend returns the recomputed figure, so the reporter sees
    // their contribution land rather than a generic acknowledgement.
    if (msgEl) msgEl.textContent = res.message;

    await refreshBusNumbers(busId);
  } catch (err) {
    // A 429 carries the wait time in its message; show it as guidance
    // rather than as a failure.
    const text = String(err);
    if (msgEl) {
      msgEl.textContent = /update your report/i.test(text)
        ? text
        : `Report failed: ${text}`;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------
// Fleet management (Manage page)
// ---------------------------------------------------------------------
async function loadFleet() {
  try {
    fleet = await invoke("list_buses");
    markBackendUp();
    renderFleet();
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    fleetListEl.innerHTML = `<div class="empty">Couldn't load the fleet: ${esc(err)}</div>`;
    fleetTagEl.textContent = "unavailable";
  }
}

function renderFleet() {
  fleetTagEl.textContent = `${fleet.length} bus${fleet.length === 1 ? "" : "es"}`;

  if (!fleet.length) {
    fleetListEl.innerHTML = '<div class="empty">No buses in the fleet yet. Add one above.</div>';
    return;
  }

  fleetListEl.innerHTML = fleet
    .map((bus) => {
      const pending = pendingDeleteId === bus.id;
      const onboard = bus.active_passengers;

      const confirmBlock = pending
        ? `<div class="delete-confirm">
            <small>Type <b>${esc(bus.bus_number)}</b> to confirm. This cannot be undone.</small>
            <input type="text" data-confirm-input="${bus.id}" placeholder="${esc(bus.bus_number)}" autocapitalize="characters" autocomplete="off" />
            <div class="bus-actions">
              <button class="action-btn danger" data-confirm-del="${bus.id}">
                ${deleteNeedsForce ? "Delete bus and its history" : "Delete permanently"}
              </button>
              <button class="action-btn secondary" data-cancel-del="${bus.id}">Cancel</button>
            </div>
            <div class="action-msg" id="del-msg-${bus.id}"></div>
          </div>`
        : "";

      return `<div class="fleet-row ${pending ? "pending" : ""}">
        <div class="fleet-head">
          <div>
            <div class="fleet-name">${esc(bus.bus_number)}</div>
            <div class="fleet-sub">${esc(bus.route_number)} &middot; ${esc(bus.route_name)}</div>
            <div class="fleet-sub">${bus.capacity} capacity &middot; ${onboard} on board now</div>
          </div>
          ${pending ? "" : `<button class="icon-btn" data-del="${bus.id}" title="Delete ${esc(bus.bus_number)}"><i class="bi bi-trash"></i></button>`}
        </div>
        ${confirmBlock}
      </div>`;
    })
    .join("");

  fleetListEl.querySelectorAll("[data-del]").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingDeleteId = Number(btn.dataset.del);
      deleteNeedsForce = false;
      deleteTypedValue = "";
      fleetMsgEl.textContent = "";
      renderFleet();
      fleetListEl.querySelector(`[data-confirm-input="${pendingDeleteId}"]`)?.focus();
    });
  });

  fleetListEl.querySelectorAll("[data-cancel-del]").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingDeleteId = null;
      deleteNeedsForce = false;
      deleteTypedValue = "";
      renderFleet();
    });
  });

  fleetListEl.querySelectorAll("[data-confirm-del]").forEach((btn) => {
    btn.addEventListener("click", () => doDeleteBus(Number(btn.dataset.confirmDel)));
  });

  // A re-render (e.g. after the backend asked for force) would
  // otherwise wipe what the user already typed.
  if (pendingDeleteId != null && deleteTypedValue) {
    const input = fleetListEl.querySelector(`[data-confirm-input="${pendingDeleteId}"]`);
    if (input) input.value = deleteTypedValue;
  }
}

async function doDeleteBus(busId) {
  const msgEl = document.getElementById(`del-msg-${busId}`);
  const input = fleetListEl.querySelector(`[data-confirm-input="${busId}"]`);
  const confirm = input ? input.value : "";

  deleteTypedValue = confirm;

  if (!adminToken.trim()) {
    if (msgEl) msgEl.textContent = "Enter the admin token above before deleting.";
    return;
  }

  if (msgEl) msgEl.textContent = "Deleting\u2026";

  try {
    const res = await invoke("delete_bus", {
      busId,
      confirm,
      // Never force on the first attempt. The backend refuses and
      // tells us exactly what would be destroyed, and the user gets
      // to see that before the second press does it.
      force: deleteNeedsForce,
      adminToken,
    });

    pendingDeleteId = null;
    deleteNeedsForce = false;
    deleteTypedValue = "";

    dropBusMarker(busId);
    candidates = candidates.filter((c) => c.bus.id !== busId);
    if (selectedBusId === busId) selectedBusId = null;
    if (currentRide && currentRide.bus_id === busId) {
      currentRide = null;
      renderRideControls();
    }

    await loadFleet();
    await loadRoutes();
    renderList();
    renderSelected();

    // The row that held del-msg-<id> is gone along with the bus, so
    // the outcome goes on the fleet card itself.
    fleetMsgEl.textContent = res.message;
  } catch (err) {
    const message = String(err);

    // The backend signals "there's history attached, ask again with
    // force" by refusing once. Surface its wording and arm the second
    // press rather than silently retrying.
    if (/force=true/i.test(message)) {
      deleteNeedsForce = true;
      renderFleet();
      const armed = document.getElementById(`del-msg-${busId}`);
      if (armed) armed.textContent = message;
      return;
    }

    if (msgEl) msgEl.textContent = message;
  }
}

async function doAddBus() {
  const routeId = Number(newBusRouteEl.value);
  const busNumber = newBusNumberEl.value.trim();
  const capacity = Number(newBusCapacityEl.value);

  if (!routeId) {
    addBusMsgEl.textContent = "Pick a route first.";
    return;
  }

  addBusBtnEl.disabled = true;
  addBusMsgEl.textContent = "Adding\u2026";

  try {
    const bus = await invoke("create_bus", {
      routeId,
      busNumber,
      capacity,
      adminToken: adminToken.trim() || null,
    });

    addBusMsgEl.textContent = `Added ${bus.bus_number} to route ${bus.route_number}.`;
    newBusNumberEl.value = "";

    await loadFleet();
    // Routes carry their buses, so the Predict page won't offer the
    // new bus until this reloads.
    await loadRoutes();
  } catch (err) {
    addBusMsgEl.textContent = String(err);
  } finally {
    addBusBtnEl.disabled = false;
  }
}

// ---------------------------------------------------------------------
// Live arrivals board
//
// The stop-centred view: everything heading to one place, soonest
// first, with how full each one is. Only workable now that the ETA is
// route-aware - a board built on straight-line distance would list
// buses that had already driven past.
// ---------------------------------------------------------------------
function populateBoardStops() {
  if (!boardStopEl) return;
  const previous = boardStopEl.value;

  boardStops = [];
  for (const route of routes) {
    for (const stop of route.stops) {
      boardStops.push({ id: stop.id, name: stop.name, route });
    }
  }

  boardStopEl.innerHTML = boardStops
    .map(
      (s) =>
        `<option value="${s.id}">${esc(s.name)} — ${esc(s.route.route_number)}</option>`
    )
    .join("");

  if (previous && boardStops.some((s) => String(s.id) === previous)) {
    boardStopEl.value = previous;
  }
}

async function loadBoard() {
  if (!boardStopEl || !boardStopEl.value) return;

  const stopId = Number(boardStopEl.value);
  const includeUnknown = boardIncludeEl.checked;

  try {
    const board = await invoke("get_stop_arrivals", {
      stopId,
      includeUnknown,
    });

    // The user may have switched stops while this was in flight.
    if (Number(boardStopEl.value) !== stopId) return;

    markBackendUp();
    const fetchedAt = Date.now();

    boardSummaryEl.textContent = board.message;
    boardUpdatedEl.textContent = new Date().toLocaleTimeString();

    if (!board.arrivals.length) {
      boardListEl.innerHTML = `<div class="empty">${esc(board.message)}</div>`;
      return;
    }

    boardListEl.innerHTML = board.arrivals
      .map((a) => {
        const pct = Math.round(a.overall_fullness);
        const color = bandColor(pct);
        const trend =
          a.trend && a.trend !== "unknown" ? TREND_LABEL[a.trend] : "";
        const etaAttrs = a.eta
          ? ` data-eta-at="${fetchedAt}" data-eta-status="${esc(a.eta.status)}"` +
            (a.eta.eta_seconds != null ? ` data-eta-secs="${a.eta.eta_seconds}"` : "") +
            (a.eta.eta_max_seconds != null ? ` data-eta-max="${a.eta.eta_max_seconds}"` : "")
          : "";
        return `<div class="arrival">
          <div class="arrival-head">
            <div class="route">
              <div class="number">${esc(a.route_number)}</div>
              <div class="route-name">${esc(a.bus_number)}</div>
            </div>
            <div class="eta ${etaClass(a.eta)}"><b class="eta-main"${etaAttrs}>${etaHeadline(a.eta)}</b>
              <span>${esc(etaDetail(a.eta)) || esc(a.eta.message)}</span>
            </div>
          </div>
          <div class="bus-meta">
            <div class="mini-bar"><div class="fill" style="width:${Math.min(100, pct)}%;background:${color}"></div></div>
            <div class="status" style="color:${color}">${pct}% full</div>
            <div class="confidence">${esc(crowdSourceLabel(a))}${trend ? ` &middot; ${trend}` : ""}</div>
          </div>
          ${
            a.eta.confidence === "low" && a.eta.status !== "no_data"
              ? `<div class="arrival-note">${esc(a.eta.message)}</div>`
              : ""
          }
        </div>`;
      })
      .join("");
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    boardListEl.innerHTML = `<div class="empty">Couldn't load arrivals: ${esc(err)}</div>`;
  }
}

// ---------------------------------------------------------------------
// Demo mode
// ---------------------------------------------------------------------
function renderDemo() {
  const running = demoState?.running === true;
  const available = demoState?.available !== false;

  demoBannerEl.classList.toggle("show", running);
  if (running) {
    demoBannerTextEl.textContent =
      `Demo mode — all crowd data on screen is simulated (${demoState.simulated_buses.length} buses)`;
  }

  demoTagEl.textContent = running ? "Running" : available ? "Off" : "Disabled";
  demoTagEl.style.color = running ? "var(--yellow)" : "var(--muted)";

  demoToggleEl.disabled = !available;
  demoToggleEl.textContent = running ? "Stop demo mode" : "Start demo mode";
  demoToggleEl.classList.toggle("danger", running);

  if (demoState?.message) demoMessageEl.textContent = demoState.message;

  if (running && demoState.simulated_buses.length) {
    demoBusesEl.innerHTML = demoState.simulated_buses
      .map(
        (b) => `<div class="sim-row">
          <span>${esc(b.bus_number)}</span>
          <span>${b.simulated_riders}/${b.capacity} riders &middot; ${Math.round(b.speed_kmh)} km/h</span>
        </div>`
      )
      .join("");
  } else {
    demoBusesEl.innerHTML = "";
  }
}

async function refreshDemo() {
  try {
    demoState = await invoke("get_demo_status");
    markBackendUp();
    renderDemo();
    // The simulated fleet moves faster than any other screen, so while
    // it's running and visible it gets its own shorter timer on top of
    // the page loop. Nothing to watch when it's off.
    if (demoState.running && currentPage === "manage") startDemoPolling();
    else stopDemoPolling();
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
  }
}

function startDemoPolling() {
  if (demoPollTimer) return;
  demoPollTimer = setInterval(async () => {
    if (document.hidden) return;
    try {
      demoState = await invoke("get_demo_status");
      renderDemo();
      if (!demoState.running) stopDemoPolling();
    } catch {
      // ignore; next tick will retry
    }
  }, 5000);
}

function stopDemoPolling() {
  if (!demoPollTimer) return;
  clearInterval(demoPollTimer);
  demoPollTimer = null;
}

async function toggleDemo() {
  const running = demoState?.running === true;
  demoToggleEl.disabled = true;
  demoMsgEl.textContent = running ? "Stopping\u2026" : "Starting\u2026";

  try {
    demoState = running
      ? await invoke("stop_demo", { purge: true })
      : await invoke("start_demo");

    demoMsgEl.textContent = demoState.message;
    renderDemo();

    if (demoState.running) startDemoPolling();
    else stopDemoPolling();

    // Every number on screen just changed meaning, so pull fresh ones
    // instead of leaving simulated and real figures mixed together.
    await pollAllBuses();
    await refreshCandidates();
    await loadFleet();
  } catch (err) {
    demoMsgEl.textContent = String(err);
  } finally {
    demoToggleEl.disabled = false;
  }
}

async function resetDemo() {
  demoResetEl.disabled = true;
  demoMsgEl.textContent = "Clearing\u2026";
  try {
    const res = await invoke("reset_demo");
    demoMsgEl.textContent = res.message;
    await refreshDemo();
    await pollAllBuses();
    await refreshCandidates();
    await loadFleet();
  } catch (err) {
    demoMsgEl.textContent = String(err);
  } finally {
    demoResetEl.disabled = false;
  }
}

// ---------------------------------------------------------------------
// Rendering: selected route detail (gauge, recommendation, forecast)
// ---------------------------------------------------------------------
function resetSelectedPanels() {
  selectedTagEl.textContent = "Select a bus";
  historyTagEl.textContent = "Select a route";
  forecastTagEl.textContent = "Select a route";
  levelEl.textContent = "No route selected";
  levelEl.style.color = "var(--muted)";
  gaugeEl.style.background = "conic-gradient(#20333f 0 100%)";
  gaugePctEl.textContent = "\u2014";
  detailEl.textContent = "Select a bus from the list to inspect its prediction and history.";
  nextEl.textContent = "\u2014";
  nextEtaEl.textContent = "\u2014";
  if (crowdSourceEl) {
  crowdSourceEl.textContent = "—";
}  recommendTextEl.textContent = "Pick a route to see the best travel option.";
  patternEl.textContent = "Select a route to see how its number is calculated.";
  if (confidenceInfoEl) {
    confidenceInfoEl.textContent =
      "Select a route to see how much of its number was measured and how much was forecast.";
  }
  betterEl.textContent = "Compare the available buses above instead of assuming the fastest bus is the best one.";
  timeBarsEl.innerHTML = "";
  daysEl.innerHTML = "";
  clearChart();
}

function renderSelected() {
  const c = candidates.find((x) => x.bus.id === selectedBusId && !x.error);
  if (!c) {
    resetSelectedPanels();
    return;
  }

  const { bus, route, fromStop, status, prediction } = c;
  const pct = Math.round(prediction.final_fullness);
  const color = colorFor(prediction.status);

  selectedTagEl.textContent = bus.bus_number;
  historyTagEl.textContent = `${bus.bus_number} forecast`;
  forecastTagEl.textContent = bus.bus_number;

  gaugeEl.style.background = `conic-gradient(${color} 0 ${Math.min(100, pct)}%, #20333f ${Math.min(100, pct)}% 100%)`;
  gaugePctEl.textContent = pct + "%";
  levelEl.textContent = prediction.status;
  levelEl.style.color = color;
  detailEl.textContent = prediction.message;

  // Along-route distance, not crow-flies - on a route that loops,
  // the two differ by several kilometres.
  nextEl.textContent =
    c.eta?.distance_meters != null
      ? formatDistance(c.eta.distance_meters)
      : "No live position";

  nextEtaEl.textContent = c.eta ? etaHeadline(c.eta) : "No estimate";
  if (crowdSourceEl) {
  crowdSourceEl.textContent = crowdSourceLabel(status);
}

  // Spell out both signals *and* how much each was trusted, since the
  // blend is now weighted by evidence rather than a fixed 50/50.
  const parts = [];
  if (status.active_passengers > 0) {
    parts.push(
      `${Math.round(status.passenger_fullness)}% from ${status.active_passengers} phone${status.active_passengers === 1 ? "" : "s"} aboard (weight ${status.passenger_weight.toFixed(2)})`
    );
  }
  if (status.manual_fullness != null) {
    parts.push(
      `${Math.round(status.manual_fullness)}% from ${status.reporter_count} rider report${status.reporter_count === 1 ? "" : "s"} (weight ${status.report_weight.toFixed(2)})`
    );
  }
  // The blend is evidence-weighted, so the split has to be read off the
  // response instead of hard-coded. On a bus nobody is riding with the
  // app, the live half is worth nothing and the backend says so.
  const liveWeight = prediction.live_weight ?? 0;
  const modelWeight = prediction.model_weight ?? 1;

  patternEl.textContent = parts.length
    ? `${parts.join(" and ")}, giving ${Math.round(status.overall_fullness)}% live \u2014 weighted ${Math.round(liveWeight * 100)}/${Math.round(modelWeight * 100)} against a ${Math.round(prediction.predicted_fullness)}% ML forecast.`
    : `No live signal on this bus yet, so the ${Math.round(prediction.final_fullness)}% figure is the ML forecast alone.`;

  if (confidenceInfoEl) {
    const label = CONFIDENCE_LABEL[prediction.confidence] || "Unrated";
    const samples = prediction.observed_samples ?? 0;

    // Two independent ways to be wrong, so both get stated: no live
    // signal, and a model that has never seen this bus in the real
    // world. Collapsing them into one number would hide whichever is
    // worse.
    const modelNote = samples
      ? `The model has ${samples} real observation${samples === 1 ? "" : "s"} of this bus to learn from.`
      : "The model has no real observations of this bus yet \u2014 its forecast comes from the synthetic baseline.";

    confidenceInfoEl.textContent =
      `${label}: ${Math.round(liveWeight * 100)}% of this figure came from live signals, ${Math.round(modelWeight * 100)}% from the forecast. ${modelNote}`;
  }

  const alt = candidates
    .filter((x) => !x.error && x.bus.id !== bus.id)
    .sort((a, b) => a.prediction.final_fullness - b.prediction.final_fullness)[0];
  if (alt) {
    const altDist = formatDistance(alt.distance) || "no live GPS yet";
    recommendTextEl.textContent = `${alt.bus.bus_number} is currently the lower-crowd alternative at ${Math.round(alt.prediction.final_fullness)}% (${altDist}).`;
    betterEl.textContent = `${alt.bus.bus_number} is lower-crowd than ${bus.bus_number} right now \u2014 ${Math.round(alt.prediction.final_fullness)}% vs ${pct}%.`;
  } else {
    recommendTextEl.textContent = "This is the only direct bus for the selected journey.";
    betterEl.textContent = "No alternative bus is available for this exact journey.";
  }

  loadForecast(bus.id, fromStop.id);
}

async function loadForecast(busId, stopId) {
  timeBarsEl.innerHTML = '<div class="empty" style="padding:10px">Loading\u2026</div>';
  daysEl.innerHTML = "";
  try {
    const forecast = await invoke("get_bus_forecast", { busId, stopId });
    if (selectedBusId !== busId) return; // user moved on before this resolved

    const sampleHours = [0, 3, 6, 9, 12, 15, 18, 21];
    timeBarsEl.innerHTML = sampleHours
      .map((h) => {
        const point = forecast.hourly.find((p) => p.hour_of_day === h);
        const v = point ? point.predicted_fullness : 0;
        const label = h === 0 ? "12AM" : h < 12 ? `${h}AM` : h === 12 ? "12PM" : `${h - 12}PM`;
        return `<div class="bwrap"><div class="b" style="height:${Math.max(2, v)}%;background:${bandColor(v)}"></div><label>${label}</label></div>`;
      })
      .join("");

    const dayNames = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
    daysEl.innerHTML = forecast.weekly
      .map((p) => {
        const v = Math.round(p.predicted_fullness);
        const cls = v > 80 ? "hot" : v >= 50 ? "warm" : "cool";
        const label = v > 80 ? "High" : v >= 50 ? "Med" : "Low";
        return `<div class="day ${cls}">${dayNames[p.day_of_week]}<div class="circle">${v}</div>${label}</div>`;
      })
      .join("");

    drawChart(forecast.hourly);
  } catch (err) {
    timeBarsEl.innerHTML = `<div class="empty" style="padding:10px">Couldn't load forecast: ${esc(err)}</div>`;
  }
}

// ---------------------------------------------------------------------
// Lightweight canvas line chart (no external chart library / CDN
// dependency, so this keeps working offline and in packaged builds)
// ---------------------------------------------------------------------
function clearChart() {
  const ctx = chartEl.getContext("2d");
  ctx.clearRect(0, 0, chartEl.width, chartEl.height);
}

function drawChart(hourly) {
  const dpr = window.devicePixelRatio || 1;
  const rect = chartEl.parentElement.getBoundingClientRect();
  chartEl.width = rect.width * dpr;
  chartEl.height = rect.height * dpr;
  chartEl.style.width = rect.width + "px";
  chartEl.style.height = rect.height + "px";

  const ctx = chartEl.getContext("2d");
  ctx.scale(dpr, dpr);
  const w = rect.width;
  const h = rect.height;
  const padL = 30, padR = 10, padT = 10, padB = 20;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle = "#19303d";
  ctx.fillStyle = "#718998";
  ctx.font = "9px DM Sans";
  [0, 25, 50, 75, 100].forEach((v) => {
    const y = padT + plotH - (v / 100) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText(v + "%", 2, y + 3);
  });

  const points = hourly.map((p, i) => ({
    x: padL + (i / (hourly.length - 1)) * plotW,
    y: padT + plotH - (Math.min(100, p.predicted_fullness) / 100) * plotH,
  }));

  ctx.beginPath();
  ctx.moveTo(points[0].x, padT + plotH);
  points.forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, padT + plotH);
  ctx.closePath();
  ctx.fillStyle = "rgba(85,230,208,.08)";
  ctx.fill();

  ctx.beginPath();
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.strokeStyle = "#55e6d0";
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = "#55e6d0";
  points.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#718998";
  hourly.forEach((p, i) => {
    if (i % 3 !== 0) return;
    const label = p.hour_of_day === 0 ? "12A" : p.hour_of_day < 12 ? `${p.hour_of_day}A` : p.hour_of_day === 12 ? "12P" : `${p.hour_of_day - 12}P`;
    ctx.fillText(label, points[i].x - 8, h - 4);
  });
}

// ---------------------------------------------------------------------
// My live tracking (GPS -> automatic backend pings, from lib.rs)
// ---------------------------------------------------------------------
function renderMatchPill(status) {
  if (!status) {
    myMatchWrapEl.innerHTML = "";
    return;
  }
  const pct = Math.round(status.overall_fullness);
  myMatchWrapEl.innerHTML = `<div class="match-pill">On ${esc(status.bus_number)} &middot; ${pct}% full</div>`;
}

async function maybeNotify(status) {
  const bad = status.overall_fullness > 80; // matches "Leave Later"/"Bus Full" territory
  const prev = lastNotifiedStatus.get(status.bus_id);
  if (bad && prev !== "bad") {
    lastNotifiedStatus.set(status.bus_id, "bad");
    try {
      await invoke("send_user_notification", {
        title: "Your bus is filling up",
        body: `${status.bus_number} is now at ${Math.round(status.overall_fullness)}% full.`,
      });
    } catch {
      // Notification permission may be denied - not fatal, just skip it.
    }
  } else if (!bad) {
    lastNotifiedStatus.set(status.bus_id, "ok");
  }
}

async function startTracking() {
  if (trackingStarted) return;
  trackBtnEl.disabled = true;
  trackBtnEl.textContent = "Requesting permission\u2026";
  try {
    await invoke("start_location_tracking");
    trackingStarted = true;
    trackBtnEl.textContent = "Live tracking active";
  } catch (err) {
    trackBtnEl.disabled = false;
    trackBtnEl.textContent = "Enable live tracking";
    myCoordsEl.textContent = `Error: ${err}`;
    if (mapTagEl) mapTagEl.textContent = "GPS unavailable";
  }
}

function setupTracking() {
  listen("location-update", (event) => {
    const { latitude, longitude, speed_kmh } = event.payload;
    myCoordsEl.textContent = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
    mySpeedEl.textContent = speed_kmh == null ? "\u2014" : `${speed_kmh.toFixed(1)} km/h`;
    updateUserMarker(latitude, longitude);
  });

  listen("bus-status-update", (event) => {
    renderMatchPill(event.payload);
    maybeNotify(event.payload);
    updateBusMarker(event.payload);
  });

  trackBtnEl.addEventListener("click", startTracking);
  checkoutBtnEl.addEventListener("click", () => doCheckOut(currentRide?.bus_id ?? null));
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  fromEl = document.getElementById("from");
  toEl = document.getElementById("to");
  predictBtn = document.getElementById("predict");
  noticeEl = document.getElementById("notice");
  countEl = document.getElementById("count");
  busListEl = document.getElementById("bus-list");
  selectedTagEl = document.getElementById("selected-tag");
  gaugeEl = document.getElementById("gauge");
  gaugePctEl = document.getElementById("gauge-pct");
  levelEl = document.getElementById("level");
  detailEl = document.getElementById("detail");
  nextEl = document.getElementById("next");
  nextEtaEl = document.getElementById("next-eta");
  recommendTextEl = document.getElementById("recommend-text");
  historyTagEl = document.getElementById("history-tag");
  timeBarsEl = document.getElementById("time-bars");
  daysEl = document.getElementById("days");
  forecastTagEl = document.getElementById("forecast-tag");
  chartEl = document.getElementById("chart");
  patternEl = document.getElementById("pattern");
  betterEl = document.getElementById("better");
  confidenceInfoEl = document.getElementById("confidence-info");
  myCoordsEl = document.getElementById("my-coords");
  mySpeedEl = document.getElementById("my-speed");
  myMatchWrapEl = document.getElementById("my-match-wrap");
  trackBtnEl = document.getElementById("track-btn");
  checkoutBtnEl = document.getElementById("checkout-btn");
  rideMsgEl = document.getElementById("ride-msg");
  onlineDotEl = document.getElementById("online-dot");
  onlineTextEl = document.getElementById("online-text");
  liveMapEl = document.getElementById("live-map");
  mapTagEl = document.getElementById("map-tag");

  demoBannerEl = document.getElementById("demo-banner");
  demoBannerTextEl = document.getElementById("demo-banner-text");
  demoTagEl = document.getElementById("demo-tag");
  demoMessageEl = document.getElementById("demo-message");
  demoToggleEl = document.getElementById("demo-toggle");
  demoResetEl = document.getElementById("demo-reset");
  demoMsgEl = document.getElementById("demo-msg");
  demoBusesEl = document.getElementById("demo-buses");

  newBusRouteEl = document.getElementById("new-bus-route");
  newBusNumberEl = document.getElementById("new-bus-number");
  newBusCapacityEl = document.getElementById("new-bus-capacity");
  addBusBtnEl = document.getElementById("add-bus-btn");
  addBusMsgEl = document.getElementById("add-bus-msg");
  adminTokenEl = document.getElementById("admin-token");
  fleetListEl = document.getElementById("fleet-list");
  fleetTagEl = document.getElementById("fleet-tag");
  fleetMsgEl = document.getElementById("fleet-msg");
  boardStopEl = document.getElementById("board-stop");
  boardIncludeEl = document.getElementById("board-include-unknown");
  boardListEl = document.getElementById("board-list");
  boardSummaryEl = document.getElementById("board-summary");
  boardUpdatedEl = document.getElementById("board-updated");
  crowdSourceEl = document.getElementById("crowd-source");
  refreshBtnEl = document.getElementById("refresh-btn");
  refreshStampEl = document.getElementById("refresh-stamp");
  autoRefreshEl = document.getElementById("auto-refresh");

  refreshBtnEl.addEventListener("click", () => {
    // A manual press is also a statement that the automatic schedule
    // isn't keeping up, so reset the backoff and start counting again
    // from now.
    refreshFailures = 0;
    refreshCurrentPage({ manual: true });
  });

  autoRefreshEl.addEventListener("change", () => setAutoRefresh(autoRefreshEl.checked));

  // A phone in a pocket shouldn't be polling. Coming back from the
  // background, the numbers are by definition stale, so fetch at once
  // rather than waiting out the interval.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAutoRefresh();
    else if (autoRefresh) refreshCurrentPage();
  });
  window.addEventListener("focus", () => {
    if (autoRefresh && lastRefreshAt != null && Date.now() - lastRefreshAt > STALE_AFTER_MS) {
      refreshCurrentPage();
    }
  });
  window.addEventListener("online", () => {
    refreshFailures = 0;
    refreshCurrentPage({ manual: true });
  });
  window.addEventListener("offline", () => markBackendDown());

  fromEl.addEventListener("change", () => {
    if (fromEl.value === toEl.value) {
      const opt = [...toEl.options].find((o) => o.value !== fromEl.value);
      if (opt) toEl.value = opt.value;
    }
  });

  predictBtn.addEventListener("click", runPredict);

  boardStopEl.addEventListener("change", loadBoard);
  boardIncludeEl.addEventListener("change", loadBoard);

  addBusBtnEl.addEventListener("click", doAddBus);
  demoToggleEl.addEventListener("click", toggleDemo);
  demoResetEl.addEventListener("click", resetDemo);

  // Held in memory only - never persisted, so closing the app forgets it.
  adminTokenEl.addEventListener("input", () => {
    adminToken = adminTokenEl.value;
  });

  setupNavigation();
  initMap();
  setupTracking();
  resetSelectedPanels();
  renderRideControls();

  // Routes first, then hand the schedule to the loop: everything else
  // (bus positions, demo state, fleet) is driven by whichever page is
  // on screen.
  restoreAlarms();

  // Something on screen before the network answers. Replaced the
  // moment real data lands; clearly labelled as stale until then.
  renderCachedSnapshot();

  loadRoutes().then(() => {
    refreshDemo();
    startAutoRefresh({ immediate: true });
    connectStream();
  });
  // Start location tracking automatically on app startup instead of
  // waiting for the user to click "Enable live tracking".
  startTracking();
});