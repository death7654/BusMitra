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

// A blank list with just a sentence in it reads as unfinished. Every
// "nothing here yet" message gets a Bootstrap icon above the text
// instead, so empty states look designed rather than like a bug.
function emptyState(icon, html) {
  return `<div class="empty"><i class="bi ${icon}"></i>${html}</div>`;
}

// Briefly pulses an element so a value that just changed (the gauge,
// the selected-route tag) reads as "this just updated" rather than
// snapping silently. Safe to call repeatedly - it just restarts itself.
function flash(el) {
  if (!el) return;
  el.classList.remove("flash");
  // Force a reflow so removing+re-adding the class restarts the
  // animation even if it's already running from a previous update.
  void el.offsetWidth;
  el.classList.add("flash");
}

// ---------------------------------------------------------------------
// Route identity colors
// ---------------------------------------------------------------------
// A small fixed palette, picked to stay clear of the semantic colors
// used elsewhere (green/yellow/orange/red for crowd status, blue for
// weather, cyan for brand/interactive) so a route's color never gets
// mistaken for a status. Same route number always hashes to the same
// entry, so a route reads as the same color on Predict, Board and Fleet.
const ROUTE_PALETTE = ["#a78bfa", "#f472b6", "#60a5fa", "#fb923c", "#34d399", "#818cf8", "#fb7185", "#a3e635"];

function routeColor(routeNumber) {
  const s = String(routeNumber ?? "");
  let hash = 0;
  for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  return ROUTE_PALETTE[hash % ROUTE_PALETTE.length];
}

// Returns a style="" attribute (custom properties only - see the
// .number rule in styles.css) so callers just splice it into a
// template literal wherever a route-number badge is rendered.
function routeColorVars(routeNumber) {
  const hex = routeColor(routeNumber);
  return `style="--rc:${hex};--rc-bg:${hex}1a;--rc-border:${hex}66"`;
}

// ---------------------------------------------------------------------
// Haptics
// ---------------------------------------------------------------------
// Prefer a native Tauri haptics plugin if one happens to be registered,
// but never assume it exists - fall back to the standard Web Vibration
// API, and no-op silently on platforms/webviews that support neither
// (desktop, iOS Safari webviews, etc). A confirmation beep nobody feels
// is fine; a thrown error from a missing plugin is not.
function haptic(pattern = 10, tauriStyle = "light") {
  try {
    const tauriHaptics = window.__TAURI__?.haptics;
    if (tauriHaptics?.impactFeedback) {
      tauriHaptics.impactFeedback(tauriStyle).catch(() => {});
      return;
    }
  } catch {}
  try {
    navigator.vibrate?.(pattern);
  } catch {}
}

// ---------------------------------------------------------------------
// Skeleton loaders - shaped like the content that's about to replace
// them so the wait reads as progress rather than a blank/generic spinner.
// ---------------------------------------------------------------------
function skeletonBusList(count = 3) {
  const row = `
    <div class="skeleton-bus">
      <div class="sk-row">
        <div class="sk-row" style="margin-bottom:0">
          <div class="skeleton-block sk-number"></div>
          <div class="skeleton-block sk-name"></div>
        </div>
        <div class="skeleton-block sk-eta"></div>
      </div>
      <div class="skeleton-block sk-bar"></div>
    </div>`;
  return row.repeat(count);
}

function skeletonFleetList(count = 4) {
  const row = `
    <div class="skeleton-fleet">
      <div class="skeleton-block sk-dot"></div>
      <div class="sk-lines">
        <div class="skeleton-block sk-line"></div>
        <div class="skeleton-block sk-line"></div>
      </div>
    </div>`;
  return row.repeat(count);
}

function skeletonBars(count = 8) {
  const heights = [40, 65, 30, 80, 55, 70, 35, 60, 45, 75, 50, 25];
  let out = '<div class="skeleton-bars">';
  for (let i = 0; i < count; i++) {
    out += `<div class="skeleton-block sk-col" style="height:${heights[i % heights.length]}%"></div>`;
  }
  return out + "</div>";
}

// ---------------------------------------------------------------------
// State
// ---------------------------------------------------------------------
let routes = [];        // from get_routes
let candidates = [];    // computed per Predict click
let selectedBusId = null;
let trackingStarted = false;
let lastNotifiedStatus = new Map(); // bus_id -> last status we already notified about
let lastKnownPosition = { latitude: null, longitude: null }; // filled by location-update events, used for SOS/health reports

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

// Weather
let weatherData = null;
let weatherLastFetchedAt = 0;
const WEATHER_REFRESH_MS = 10 * 60 * 1000; // matches the backend's own cache TTL

// DOM refs (filled in on DOMContentLoaded)
let fromEl, toEl, predictBtn, swapBtnEl, noticeEl, countEl, busListEl;
let selectedTagEl, gaugeEl, gaugePctEl, levelEl, detailEl, nextEl, nextEtaEl;
let recommendTextEl, historyTagEl, timeBarsEl, daysEl;
let forecastTagEl, chartEl, insightsBodyEl, insightsTagEl;
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
let weatherChipEl, weatherIconEl, weatherTextEl, weatherAdvisoryEl, weatherAdvisoryTextEl;
let outageTagEl, outageBannerEl, outageReasonEl, outageReportBtnEl, outageMsgEl;

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

  // Weather is cheap to check (guarded by its own timestamp, cached
  // server-side too) so it rides along on every page's refresh rather
  // than needing its own schedule.
  jobs.push(maybeRefreshWeather());

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
    case "sos":
      // Nothing to poll here - the page is driven entirely by local
      // state (trusted contact, captured photos) and user action.
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
    // A stronger pattern than the light confirmation taps elsewhere -
    // this is the one haptic that fires without the person tapping
    // anything first, so it needs to actually get noticed.
    haptic([30, 60, 30], "heavy");

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
const LAST_SEARCH_KEY = "BusMitra:last-search:v1";

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
            <div class="route"><div class="number" ${routeColorVars(c.routeNumber)}>${esc(c.routeNumber)}</div>
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

// Remembers the last journey searched, so a returning rider doesn't
// have to reselect two stops from scratch every time they open the app.
function saveLastSearch(from, to) {
  try {
    localStorage.setItem(LAST_SEARCH_KEY, JSON.stringify({ from, to }));
  } catch {
    // Non-fatal.
  }
}

function loadLastSearch() {
  try {
    return JSON.parse(localStorage.getItem(LAST_SEARCH_KEY) || "null");
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------
// First-run onboarding tip
// ---------------------------------------------------------------------
const ONBOARDING_KEY = "BusMitra:onboarding-dismissed:v1";

function setupOnboardingTip() {
  const tip = document.getElementById("onboarding-tip");
  const dismissBtn = document.getElementById("onboarding-dismiss");
  if (!tip) return;

  let dismissed = false;
  try {
    dismissed = localStorage.getItem(ONBOARDING_KEY) === "1";
  } catch {
    // Non-fatal - worst case the tip shows again next launch.
  }
  if (dismissed) {
    tip.classList.add("hidden");
    return;
  }

  dismissBtn?.addEventListener("click", () => {
    tip.classList.add("hidden");
    try {
      localStorage.setItem(ONBOARDING_KEY, "1");
    } catch {
      // Non-fatal.
    }
  });
}

// ---------------------------------------------------------------------
// Page navigation (bottom tab bar). Only one <section class="page"> is
// visible at a time so each screen fits with minimal scrolling.
// ---------------------------------------------------------------------
// Pages reachable only through the "More" drawer rather than a primary
// tab. The drawer's own tab button (id="more-tab") lights up whenever
// one of these is the active page, so the bar still shows *something*
// is selected instead of going dark.
const DRAWER_PAGES = new Set(["prediction", "forecast", "insights", "manage", "sos"]);
let moreTabEl, drawerEl, drawerBackdropEl;

function showPage(name) {
  pageEls.forEach((el) => el.classList.toggle("active", el.dataset.page === name));
  tabEls.forEach((el) => el.classList.toggle("active", el.dataset.page === name));
  if (moreTabEl) moreTabEl.classList.toggle("active", DRAWER_PAGES.has(name));
  // The map is only ever measured correctly once its container is
  // actually visible, so re-measure it right after we reveal it.
  if (name === "map" && map) setTimeout(() => map.invalidateSize(), 0);

  currentPage = name;
  closeDrawer();

  // Arriving on a screen is exactly when its numbers matter most, so
  // fetch immediately rather than waiting out the interval. The loop
  // then re-times itself to whatever cadence this page wants.
  stopAutoRefresh();
  refreshCurrentPage({ manual: true });
}

function openDrawer() {
  if (!drawerEl) return;
  drawerEl.classList.add("open");
  drawerBackdropEl.classList.add("show");
  drawerEl.setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  if (!drawerEl) return;
  drawerEl.classList.remove("open");
  drawerBackdropEl.classList.remove("show");
  drawerEl.setAttribute("aria-hidden", "true");
}

function setupNavigation() {
  pageEls = [...document.querySelectorAll(".page")];
  tabEls = [...document.querySelectorAll(".tab")];
  tabEls.forEach((tab) => {
    // The "More" tab has no data-page of its own - it opens the drawer
    // instead of switching pages directly.
    if (tab.id === "more-tab") return;
    tab.addEventListener("click", () => showPage(tab.dataset.page));
  });

  moreTabEl = document.getElementById("more-tab");
  drawerEl = document.getElementById("more-drawer");
  drawerBackdropEl = document.getElementById("drawer-backdrop");
  moreTabEl?.addEventListener("click", () => {
    drawerEl.classList.contains("open") ? closeDrawer() : openDrawer();
  });
  drawerBackdropEl?.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });
}

// Emergency / reporting DOM refs
let healthBtnEl, breakdownBtnEl;
let sosModalEl, healthModalEl, breakdownModalEl;
let sosOptionEls, sosDetailsEl, sosSubmitBtnEl, sosStatusEl;
let healthAlertBtnEl;
let breakdownBusEl, breakdownSubmitBtnEl, breakdownNotesEl, breakdownStatusEl;
let selectedSosType = null;

// ---------------------------------------------------------------------
// Dedicated SOS page DOM refs
// ---------------------------------------------------------------------
let trustedNameEl, trustedPhoneEl, trustedContactTagEl, trustedContactMsgEl;
let pickContactBtnEl, saveContactBtnEl;
let sosTriggerBtnEl, sosTriggerTagEl, sosTriggerStatusEl;
let sosOpenDetailedBtnEl;
let cameraFlowEl, cameraFlowLabelEl, cameraFlowStatusEl, cameraVideoEl, cameraCanvasEl, cameraSkipBtnEl;
let evidenceFrontEl, evidenceBackEl;

// The trusted contact's number, pulled once from this phone's own
// contacts (or typed in once) and remembered locally from then on -
// nothing here ever leaves the device except inside the SOS report
// the person explicitly sends.
let trustedContact = { name: "", phone: "" };

// ---- App-wide default SOS contact -----------------------------------
// Used whenever the rider hasn't saved a trusted contact of their own, so
// an SOS always reaches a real person instead of only opening a dialer.
// >>> SET THIS to a number you actually monitor (family desk, campus /
// >>> transport-office security, etc.), in international format, e.g.
// >>> "+919000000000". While `phone` is blank the app falls back to
// >>> dialing 112 only, exactly as before.
const DEFAULT_SOS_CONTACT = { name: "BusMitra Safety Desk", phone: "+919747092232" };
const EMERGENCY_FALLBACK_NUMBER = "112";

// The contact an SOS will actually use: the rider's own if saved,
// otherwise the app default, otherwise nobody (112 dial only).
function effectiveSosContact() {
  if (trustedContact.phone) return { ...trustedContact, isDefault: false };
  if (DEFAULT_SOS_CONTACT.phone) return { ...DEFAULT_SOS_CONTACT, isDefault: true };
  return { name: "", phone: "", isDefault: false };
}
let capturedPhotos = { front: null, back: null };
// Set by the "Skip photos" button to bail out of an in-progress
// front/back capture sequence without waiting for either camera.
let cameraSkipRequested = false;

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

async function initMap() {
  if (!liveMapEl || typeof L === "undefined") return;
  map = L.map(liveMapEl, { zoomControl: true }).setView([20, 0], 2);

  // Tiles come through our own backend, not CARTO directly, so the
  // CARTO API key stays server-side only - read from an env var on
  // Render, never sent to this webview or committed anywhere.
  const apiBase = await invoke("get_api_base_url");
  L.tileLayer(`${apiBase}/api/tiles/voyager/{z}/{x}/{y}.png`, {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(map);

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
// Weather
// ---------------------------------------------------------------------
// Fetched with whatever position live tracking has (falls back to the
// backend's own default stop when GPS hasn't produced a fix yet), and
// cached client-side for as long as the backend caches it server-side
// - there's no point asking again before the answer could have moved.
const WEATHER_ICON = {
  clear: "bi-sun", clouds: "bi-cloud-sun", fog: "bi-cloud-fog2",
  rain: "bi-cloud-rain", snow: "bi-cloud-snow", storm: "bi-cloud-lightning-rain",
  unknown: "bi-cloud",
};

async function loadWeather() {
  try {
    const w = await invoke("get_weather", {
      latitude: lastKnownPosition ? lastKnownPosition.latitude : null,
      longitude: lastKnownPosition ? lastKnownPosition.longitude : null,
    });
    weatherData = w;
    weatherLastFetchedAt = Date.now();
    renderWeather();
  } catch (err) {
    // Weather is a nicety, not core function - a failed fetch here
    // must never touch backendUp/markBackendDown or the bus list.
    console.warn("weather fetch failed:", err);
  }
}

function maybeRefreshWeather() {
  if (Date.now() - weatherLastFetchedAt < WEATHER_REFRESH_MS) return Promise.resolve();
  return loadWeather();
}

// ---------------------------------------------------------------------
// Shared banner strip: demo-mode and the weather advisory both want the
// same slot above the page content. Showing both permanently reads as
// banner spam, so at most one is visible at a time; when both are
// relevant they alternate every few seconds instead of stacking. Demo
// mode is listed first, so if both come active at the same moment it's
// the one shown first - a simulated-data warning matters more than a
// weather tip.
// ---------------------------------------------------------------------
const BANNER_ROTATE_MS = 6000;
const bannerWants = { demo: false, weather: false };
let bannerRotateTimer = null;
let bannerRotateIndex = 0;

function applyBannerVisibility(showKey) {
  demoBannerEl?.classList.toggle("show", showKey === "demo");
  weatherAdvisoryEl?.classList.toggle("show", showKey === "weather");
}

function updateBannerRotation() {
  const active = Object.keys(bannerWants).filter((k) => bannerWants[k]);

  if (active.length <= 1) {
    clearInterval(bannerRotateTimer);
    bannerRotateTimer = null;
    applyBannerVisibility(active[0] ?? null);
    return;
  }

  if (bannerRotateTimer) return; // already rotating between the same two

  bannerRotateIndex = 0;
  applyBannerVisibility(active[bannerRotateIndex]);
  bannerRotateTimer = setInterval(() => {
    const stillActive = Object.keys(bannerWants).filter((k) => bannerWants[k]);
    if (stillActive.length <= 1) {
      updateBannerRotation();
      return;
    }
    bannerRotateIndex = (bannerRotateIndex + 1) % stillActive.length;
    applyBannerVisibility(stillActive[bannerRotateIndex]);
  }, BANNER_ROTATE_MS);
}

function setBannerWant(key, wants) {
  if (bannerWants[key] === wants) return;
  bannerWants[key] = wants;
  updateBannerRotation();
}

function renderWeather() {
  if (!weatherData || !weatherChipEl) return;

  const icon = WEATHER_ICON[weatherData.condition_category] || WEATHER_ICON.unknown;
  weatherIconEl.className = `bi ${icon}`;
  const temp = weatherData.temperature_c != null ? `${Math.round(weatherData.temperature_c)}\u00b0C` : "\u2014";
  weatherTextEl.textContent = `${temp} \u00b7 ${esc(weatherData.condition)}`;

  if (weatherAdvisoryEl) {
    if (weatherData.advisory) {
      weatherAdvisoryTextEl.textContent = weatherData.advisory;
      weatherAdvisoryEl.classList.toggle(
        "severe",
        weatherData.condition_category === "storm" || weatherData.condition_category === "snow"
      );
    }
    setBannerWant("weather", Boolean(weatherData.advisory));
  }
}


// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
// Backend data loading
// ---------------------------------------------------------------------
let startupAutoPredictDone = false;

async function loadRoutes() {
  try {
    routes = await invoke("get_routes");
    markBackendUp();
    onlineTextEl.textContent = "Prediction engine online";
    populateStopSelects();
    populateRouteSelect();
    populateBoardStops();
    fitMapToStops();

    // First successful load only: if the restored from/to (see
    // populateStopSelects) matches the last journey actually searched,
    // run it automatically so returning riders see results right away
    // instead of an empty list they have to re-trigger themselves.
    if (!startupAutoPredictDone) {
      startupAutoPredictDone = true;
      const lastSearch = loadLastSearch();
      if (lastSearch && fromEl.value === lastSearch.from && toEl.value === lastSearch.to) {
        runPredict();
      }
    }
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    busListEl.innerHTML = emptyState("bi-plug", `Can't reach the backend (${esc(err)}). Check that uvicorn is running, then press the refresh button up top.`);
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
  // the user had picked. Put it back when the stops still exist. On the
  // very first population (nothing picked yet this session) fall back
  // to the last journey the person actually searched, so the app opens
  // ready to go instead of empty.
  const lastSearch = !fromEl.value && !toEl.value ? loadLastSearch() : null;
  const previousFrom = fromEl.value || lastSearch?.from || "";
  const previousTo = toEl.value || lastSearch?.to || "";

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
    outage: state.outage || emptyOutageStatus(),
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

// ---------------------------------------------------------------------
// Journeys that need a change of bus
//
// The direct-route scan in findCandidates stops at one bus. When it
// finds nothing, ask the backend planner (services/journeys.py) for
// options with a transfer. Only the first leg carries a live arrival
// and crowd figure; later legs are shown without one, because the
// connecting bus is not the one approaching its stop right now.
// ---------------------------------------------------------------------
// ---- Multi-stage planner: every way to reach the destination stop ----
let planOptions = [];        // options from the last plan_journey call
let planSort = "changes";
let planGeneration = 0;      // discards plan responses from superseded searches

const nullLast = (a, b) => (a ?? Infinity) - (b ?? Infinity);
const PLAN_SORTS = {
  changes: (a, b) => a.transfers - b.transfers || a.total_stops - b.total_stops,
  stops: (a, b) => a.total_stops - b.total_stops || a.transfers - b.transfers,
  soonest: (a, b) => nullLast(a.first_departure_seconds, b.first_departure_seconds) || a.transfers - b.transfers,
};

function planLegHtml(leg, isFirst) {
  const stops = `${leg.stops_count} stop${leg.stops_count === 1 ? "" : "s"}`;
  let live;
  if (isFirst && leg.best_bus_number && leg.eta_seconds != null) {
    const mins = Math.max(1, Math.round(leg.eta_seconds / 60));
    const full = leg.overall_fullness != null ? ` &middot; ${Math.round(leg.overall_fullness)}% full` : "";
    live = `Next: ${esc(leg.best_bus_number)} in about ${mins} min${full}`;
  } else if (isFirst) {
    live = "No live bus approaching yet";
  } else {
    live = "Connecting bus: arrival not predicted";
  }
  return `<li class="plan-stage" ${routeColorVars(leg.route_number)}>
    <div class="plan-stage-body">
      <div class="plan-route"><span class="number" ${routeColorVars(leg.route_number)}>${esc(leg.route_number)}</span><b>${isFirst ? "Board" : "Then board"} at ${esc(leg.board_stop_name)}</b></div>
      <span>Ride ${stops} to ${esc(leg.alight_stop_name)} &middot; ${live}</span>
    </div>
  </li>`;
}

function planOptionHtml(opt, isBest) {
  const changes = opt.transfers === 0 ? "Direct" : `${opt.transfers} change${opt.transfers === 1 ? "" : "s"}`;
  const wait = opt.first_departure_seconds != null
    ? ` &middot; first bus ~${Math.max(1, Math.round(opt.first_departure_seconds / 60))} min`
    : "";
  const stages = opt.legs.map((leg, i) => {
    const change = i < opt.legs.length - 1
      ? `<li class="plan-change"><i class="bi bi-arrow-repeat"></i>Change at ${esc(leg.alight_stop_name)}</li>`
      : "";
    return planLegHtml(leg, i === 0) + change;
  }).join("");
  const last = opt.legs[opt.legs.length - 1];
  return `<div class="plan${isBest ? " is-best" : ""}">
    <div class="plan-head"><b>${changes}${isBest ? '<em class="plan-best">Best</em>' : ""}</b><span>${opt.total_stops} stops in total${wait}</span></div>
    <ol class="plan-stages">${stages}<li class="plan-arrive">${esc(last.alight_stop_name)} <span>&middot; you're there</span></li></ol>
  </div>`;
}

function renderPlans() {
  const box = document.getElementById("journey-plans");
  const list = document.getElementById("plans-list");
  if (!box || !list) return;
  if (!planOptions.length) {
    box.hidden = true;
    return;
  }
  const sorted = [...planOptions].sort(PLAN_SORTS[planSort] || PLAN_SORTS.changes).slice(0, 6);
  list.innerHTML = sorted.map((opt, i) => planOptionHtml(opt, i === 0 && sorted.length > 1)).join("");
  document.getElementById("plans-count").textContent =
    `${planOptions.length} option${planOptions.length === 1 ? "" : "s"}`;
  document.getElementById("plans-title").textContent = `All routes to ${toEl?.value || "your stop"}`;
  document.querySelectorAll("#plans-sort .chip").forEach((chip) =>
    chip.classList.toggle("active", chip.dataset.sort === planSort)
  );
  box.hidden = false;
}

function hidePlans() {
  planGeneration++;
  planOptions = [];
  const box = document.getElementById("journey-plans");
  if (box) box.hidden = true;
}

// Asks the backend planner for every option to the destination. Returns
// the plan (or null on failure) and, when the search is still current,
// fills the "All routes" section. Direct buses are already on screen as
// live cards, so only trips that need a change are listed here unless
// there is no direct bus at all.
async function loadPlans(fromName, toName, { includeDirect = false } = {}) {
  const generation = ++planGeneration;
  let plan = null;
  try {
    plan = await invoke("plan_journey", { fromStop: fromName, toStop: toName });
  } catch {
    plan = null;
  }
  if (generation !== planGeneration) return plan;
  const all = plan?.options || [];
  planOptions = includeDirect ? all : all.filter((o) => o.transfers > 0);
  renderPlans();
  return plan;
}

function setupPlanner() {
  document.getElementById("plans-sort")?.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    planSort = chip.dataset.sort;
    renderPlans();
  });
}

function showNoJourney(message) {
  hidePlans();
  noticeEl.textContent = message;
  noticeEl.classList.remove("good");
  noticeEl.classList.add("show");
  busListEl.innerHTML = emptyState(
    "bi-signpost-2",
    "No bus or combination of buses found for this journey.<br>Try reversing the locations or choosing another pair of stops."
  );
}

async function showJourneyOptions(fromName, toName) {
  busListEl.innerHTML = skeletonBusList(2);
  hidePlans();

  const plan = await loadPlans(fromName, toName, { includeDirect: true });

  if (!plan) {
    showNoJourney(
      "No direct bus was found between these locations, and the journey planner could not be reached."
    );
    return;
  }
  if (!plan.options?.length) {
    showNoJourney(plan.message || "No bus or combination of buses connects these locations.");
    return;
  }

  noticeEl.textContent = `No direct bus, but ${plan.message.charAt(0).toLowerCase()}${plan.message.slice(1)}`;
  noticeEl.classList.remove("show");
  noticeEl.classList.add("good", "show");
  busListEl.innerHTML = emptyState(
    "bi-signpost-split",
    "No direct bus on this trip.<br>See the routes with changes below."
  );
}

async function runPredict() {
  const fromName = fromEl.value;
  const toName = toEl.value;
  selectedBusId = null;

  const found = findCandidates(fromName, toName);
  hidePlans();

  if (found.length === 0) {
    candidates = [];
    countEl.textContent = "0";
    renderSelected();
    await showJourneyOptions(fromName, toName);
    return;
  }

  predictBtn.disabled = true;
  predictBtn.textContent = "Loading\u2026";
  busListEl.innerHTML = skeletonBusList(Math.min(found.length, 4));
  saveLastSearch(fromName, toName);

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

  // Also list routes that need a change of bus. Not awaited: the live
  // cards above are the priority and the plan fills in when it arrives.
  loadPlans(fromName, toName);
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
  const okCandidates = candidates.filter((c) => !c.error);
  countEl.textContent = okCandidates.length;

  if (candidates.length === 0) return;

  if (suspendListRender) {
    listRenderPending = true;
    return;
  }

  // The soonest arrival is already first in the array (see the sort in
  // runPredict), but "first in a list" is easy to skim past. Marking it
  // explicitly means the one bus most people actually want doesn't
  // depend on the reader noticing list order.
  const nextUpId = okCandidates.length > 1 ? okCandidates[0].bus.id : null;

  busListEl.innerHTML = candidates
    .map((c) => {
      const open = selectedBusId === c.bus.id;
      if (c.error) {
        return `<div class="bus" data-id="${c.bus.id}">
          <div class="bus-head"><div class="route"><div class="number" ${routeColorVars(c.route.route_number)}>${esc(c.route.route_number)}</div><div class="route-name">${esc(c.bus.bus_number)}</div></div></div>
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

      const outageBadge = c.status.outage && c.status.outage.reported_out_of_service
        ? `<div class="outage-badge"><i class="bi bi-exclamation-triangle"></i> Reported not running by ${c.status.outage.outage_report_count} riders</div>`
        : "";

      const isNext = c.bus.id === nextUpId;
      const trend = c.status.trend && c.status.trend !== "unknown" ? c.status.trend : null;
      const confidenceLine = `<div class="confidence">${esc(crowdSourceLabel(c.status))}${
        trend ? ` &middot; <span class="trend-${esc(trend)}">${TREND_LABEL[trend]}</span>` : ""
      }</div>`;

      return `<div class="bus ${open ? "selected" : ""} ${riding ? "riding" : ""} ${isNext ? "next-up" : ""}" data-id="${c.bus.id}">
        <div class="bus-head">
          <div class="route"><div class="number" ${routeColorVars(c.route.route_number)}>${esc(c.route.route_number)}</div><div class="route-name">${esc(c.bus.bus_number)}${isNext ? ' <span class="next-badge">Next</span>' : ""}</div></div>
          <div class="eta ${etaClass(c.eta)}"><b class="eta-main"${etaAttrs}>${etaMain}</b><span>${etaSub}</span></div>
        </div>
        ${outageBadge}
        <div class="bus-meta">
          <div class="mini-bar"><div class="fill" style="width:${Math.min(100, pct)}%;background:${color}"></div></div>
          <div class="status" style="color:${color}">${esc(c.prediction.status)}</div>
        </div>
        <div class="expand"><div class="expand-inner">
          ${confidenceLine}
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
        </div></div>
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
    haptic();
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
    haptic();
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
    haptic();

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
// Outage reporting
// ---------------------------------------------------------------------
// A different signal from a crowd report: this says a bus might not
// be coming at all. Unlike crowd reports there's no per-device
// cooldown - the backend only starts showing a bus as reported once a
// second rider confirms the same thing, which is the safeguard here
// instead.
const OUTAGE_REASON_LABEL = {
  not_running: "Not running",
  breakdown: "Broken down",
  never_arrived: "Never arrived",
  accident: "Accident",
  other: "Other issue",
};

function emptyOutageStatus() {
  return { reported_out_of_service: false, outage_report_count: 0, outage_reasons: [], last_outage_report_at: null };
}

function renderOutage(outage) {
  if (!outageTagEl) return;
  const status = outage || emptyOutageStatus();

  if (status.reported_out_of_service) {
    outageTagEl.textContent = `${status.outage_report_count} rider${status.outage_report_count === 1 ? "" : "s"} reported`;
    outageTagEl.classList.add("reported");

    if (outageBannerEl) {
      const reasons = (status.outage_reasons || [])
        .map((r) => OUTAGE_REASON_LABEL[r] || r)
        .join(", ") || "not running";
      outageBannerEl.textContent = `\u26a0\ufe0f Reported ${esc(reasons)} by ${status.outage_report_count} rider${status.outage_report_count === 1 ? "" : "s"}. Consider the alternative bus below.`;
      outageBannerEl.classList.add("show");
    }
  } else {
    outageTagEl.textContent = "Not reported";
    outageTagEl.classList.remove("reported");
    if (outageBannerEl) outageBannerEl.classList.remove("show");
  }
}

async function doOutageReport() {
  const c = candidates.find((x) => x.bus.id === selectedBusId && !x.error);
  if (!c) return;

  const reason = outageReasonEl ? outageReasonEl.value : "not_running";
  if (outageReportBtnEl) outageReportBtnEl.disabled = true;

  try {
    const res = await invoke("submit_outage_report", { busId: c.bus.id, reason });
    if (outageMsgEl) outageMsgEl.textContent = res.message;
    if (c.status) c.status.outage = res.status;
    renderOutage(res.status);
    haptic();
  } catch (err) {
    if (outageMsgEl) outageMsgEl.textContent = `Report failed: ${err}`;
  } finally {
    if (outageReportBtnEl) outageReportBtnEl.disabled = false;
  }
}

// ---------------------------------------------------------------------
// Fleet management (Manage page)
// ---------------------------------------------------------------------
let fleetEverLoaded = false;

async function loadFleet() {
  // Only the very first load gets a skeleton - loadFleet also runs on
  // every periodic Manage-page refresh, and replacing an already-visible
  // list with a skeleton on each poll would just be flicker.
  if (!fleetEverLoaded) fleetListEl.innerHTML = skeletonFleetList();
  try {
    fleet = await invoke("list_buses");
    markBackendUp();
    fleetEverLoaded = true;
    renderFleet();
  } catch (err) {
    refreshFailures++;
    markBackendDown(err);
    fleetListEl.innerHTML = emptyState("bi-plug", `Couldn't load the fleet: ${esc(err)}`);
    fleetTagEl.textContent = "unavailable";
  }
}

function renderFleet() {
  fleetTagEl.textContent = `${fleet.length} bus${fleet.length === 1 ? "" : "es"}`;

  if (!fleet.length) {
    fleetListEl.innerHTML = emptyState("bi-truck", "No buses in the fleet yet. Add one above.");
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
            <div class="fleet-sub"><span class="route-dot" style="background:${routeColor(bus.route_number)}"></span>${esc(bus.route_number)} &middot; ${esc(bus.route_name)}</div>
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
      boardListEl.innerHTML = emptyState("bi-signpost-split", esc(board.message));
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
              <div class="number" ${routeColorVars(a.route_number)}>${esc(a.route_number)}</div>
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
    boardListEl.innerHTML = emptyState("bi-plug", `Couldn't load arrivals: ${esc(err)}`);
  }
}

// ---------------------------------------------------------------------
// Demo mode
// ---------------------------------------------------------------------
function renderDemo() {
  const running = demoState?.running === true;
  const available = demoState?.available !== false;

  setBannerWant("demo", running);
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
// ---------------------------------------------------------------------
// Insights page: how the selected bus's number was worked out
// ---------------------------------------------------------------------
const CONFIDENCE_TONE = { high: "good", medium: "ok", low: "warn", model_only: "muted" };

function renderInsightsEmpty() {
  if (insightsTagEl) insightsTagEl.textContent = "Select a bus";
  if (insightsBodyEl) {
    insightsBodyEl.innerHTML = emptyState(
      "bi-lightbulb",
      "Pick a bus on Predict to see how its crowd number is worked out."
    );
  }
}

function insightSourceRow(icon, name, detail, pct, weight) {
  const w = typeof weight === "number" ? `<span>weight ${weight.toFixed(2)}</span>` : "";
  return `<div class="ins-source"><i class="bi ${icon}"></i>` +
    `<div class="ins-source-main"><b>${esc(name)}</b><span>${esc(detail)}</span></div>` +
    `<div class="ins-source-val"><b>${pct}%</b>${w}</div></div>`;
}

function insightCompareRow(label, v, current) {
  return `<div class="ins-cmp-row${current ? " is-current" : ""}">` +
    `<span class="ins-cmp-name">${esc(label)}</span>` +
    `<div class="ins-cmp-track"><div style="width:${Math.min(100, Math.max(2, v))}%;background:${bandColor(v)}"></div></div>` +
    `<b>${v}%</b></div>`;
}

function renderInsights(c, alt) {
  if (!insightsBodyEl) return;
  const { bus, status, prediction } = c;
  const pct = Math.round(prediction.final_fullness);
  const color = colorFor(prediction.status);
  const liveW = Math.round((prediction.live_weight ?? 0) * 100);
  const modelW = 100 - liveW;
  const conf = prediction.confidence || "model_only";
  const samples = prediction.observed_samples ?? 0;

  if (insightsTagEl) insightsTagEl.textContent = bus.bus_number;

  // ---- Card 1: where the number comes from ----
  const rows = [];
  if (status.active_passengers > 0) {
    const n = status.active_passengers;
    rows.push(insightSourceRow("bi-phone", `${n} phone${n === 1 ? "" : "s"} aboard`,
      "Live GPS from riders", Math.round(status.passenger_fullness), status.passenger_weight));
  }
  if (status.manual_fullness != null) {
    const n = status.reporter_count;
    rows.push(insightSourceRow("bi-people", `${n} rider report${n === 1 ? "" : "s"}`,
      "Crowding reported by passengers", Math.round(status.manual_fullness), status.report_weight));
  }
  rows.push(insightSourceRow("bi-cpu", "ML forecast",
    "Model estimate for this bus and time", Math.round(prediction.predicted_fullness), null));

  const blend =
    (liveW > 0 ? `<div class="ins-blend-live" style="flex:${liveW} 1 0"></div>` : "") +
    (modelW > 0 ? `<div class="ins-blend-model" style="flex:${modelW} 1 0"></div>` : "");
  const blendNote = liveW > 0
    ? `Live signals read ${Math.round(status.overall_fullness)}%, blended with the forecast.`
    : "No live signal on this bus yet, so this is the forecast alone.";

  const drivers = `<div class="card">
    <div class="card-title"><h2>What's driving this estimate</h2><span class="tag">${esc(prediction.status)}</span></div>
    <div class="ins-hero"><b style="color:${color}">${pct}%</b><span style="color:${color}">full</span></div>
    <div class="ins-blend">${blend}</div>
    <div class="ins-legend">
      <span><i style="background:var(--cyan)"></i>Live <b>${liveW}%</b></span>
      <span><i style="background:var(--blue)"></i>Forecast <b>${modelW}%</b></span>
    </div>
    ${rows.join("")}
    <p class="ins-note" style="margin-top:6px">${esc(blendNote)}</p>
  </div>`;

  // ---- Card 2: how much to trust it ----
  const label = CONFIDENCE_LABEL[prediction.confidence] || "Unrated";
  const modelNote = samples
    ? `The model has ${samples} real observation${samples === 1 ? "" : "s"} of this bus to learn from.`
    : "The model has no real observations of this bus yet \u2014 its forecast comes from the synthetic baseline.";
  const trust = `<div class="card">
    <div class="card-title"><h2>How much to trust it</h2><span class="tag">Confidence</span></div>
    <span class="ins-chip ${CONFIDENCE_TONE[conf] || "muted"}"><i class="bi bi-shield-check"></i>${esc(label)}</span>
    <div class="ins-trust-split">
      <div><b>${liveW}%</b><span>from live signals</span></div>
      <div><b>${modelW}%</b><span>from the forecast</span></div>
    </div>
    <p class="ins-note">${esc(modelNote)}</p>
  </div>`;

  // ---- Card 3: better choice ----
  let better;
  if (alt) {
    const altPct = Math.round(alt.prediction.final_fullness);
    const diff = pct - altPct;
    const a = esc(alt.bus.bus_number);
    const b = esc(bus.bus_number);
    const altDist = formatDistance(alt.distance) || "no live GPS yet";
    let verdict;
    if (diff >= 5) verdict = `${a} is ${diff} points less crowded than ${b} right now (${altDist}).`;
    else if (diff <= -5) verdict = `${b} is the less crowded choice \u2014 ${-diff} points below ${a}.`;
    else verdict = `${b} and ${a} are about equally crowded right now.`;
    better = `${insightCompareRow(bus.bus_number, pct, true)}${insightCompareRow(alt.bus.bus_number, altPct, false)}
      <div class="ins-verdict"><i class="bi bi-signpost-split"></i><span>${verdict}</span></div>`;
  } else {
    better = `<p class="ins-note">No alternative bus is available for this exact journey.</p>`;
  }
  const compare = `<div class="card">
    <div class="card-title"><h2>Better choice</h2><span class="tag">Same journey</span></div>
    ${better}
  </div>`;

  insightsBodyEl.innerHTML = drivers + trust + compare;
}

function resetSelectedPanels() {
  selectedTagEl.textContent = "Select a bus";
  historyTagEl.textContent = "Select a route";
  forecastTagEl.textContent = "Select a route";
  levelEl.textContent = "No route selected";
  levelEl.style.color = "var(--muted)";
  gaugeEl.style.background = "conic-gradient(#262b34 0 100%)";
  gaugePctEl.textContent = "\u2014";
  detailEl.textContent = "Select a bus from the list to inspect its prediction and history.";
  nextEl.textContent = "\u2014";
  nextEtaEl.textContent = "\u2014";
  if (crowdSourceEl) {
  crowdSourceEl.textContent = "—";
}  recommendTextEl.textContent = "Pick a route to see the best travel option.";
  renderInsightsEmpty();
  timeBarsEl.innerHTML = "";
  daysEl.innerHTML = "";
  clearChart();
  if (outageTagEl) outageTagEl.textContent = "Select a bus";
  if (outageTagEl) outageTagEl.classList.remove("reported");
  if (outageBannerEl) outageBannerEl.classList.remove("show");
  if (outageMsgEl) outageMsgEl.textContent = "";
  lastRenderedBusId = null;
  lastRenderedPct = null;
}

let lastRenderedBusId = null;
let lastRenderedPct = null;

function renderSelected() {
  const c = candidates.find((x) => x.bus.id === selectedBusId && !x.error);
  if (!c) {
    resetSelectedPanels();
    return;
  }

  const { bus, route, fromStop, status, prediction } = c;
  const pct = Math.round(prediction.final_fullness);
  const color = colorFor(prediction.status);

  // A number changing silently every refresh reads as flicker; flashing
  // it only when the *value itself* moves (not on every poll) reads as
  // "this just updated" instead. Picking a different bus flashes the
  // whole card, since everything about it is new.
  const busChanged = bus.id !== lastRenderedBusId;
  if (busChanged) flash(document.querySelector(".gauge-card"));
  if (busChanged || pct !== lastRenderedPct) {
    flash(gaugeEl);
    flash(gaugePctEl);
  }
  if (busChanged) flash(selectedTagEl);
  lastRenderedBusId = bus.id;
  lastRenderedPct = pct;

  selectedTagEl.textContent = bus.bus_number;
  historyTagEl.textContent = `${bus.bus_number} forecast`;
  forecastTagEl.textContent = bus.bus_number;

  gaugeEl.style.background = `conic-gradient(${color} 0 ${Math.min(100, pct)}%, #262b34 ${Math.min(100, pct)}% 100%)`;
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

  const alt = candidates
    .filter((x) => !x.error && x.bus.id !== bus.id)
    .sort((a, b) => a.prediction.final_fullness - b.prediction.final_fullness)[0];
  if (alt) {
    const altDist = formatDistance(alt.distance) || "no live GPS yet";
    recommendTextEl.textContent = `${alt.bus.bus_number} is currently the lower-crowd alternative at ${Math.round(alt.prediction.final_fullness)}% (${altDist}).`;
  } else {
    recommendTextEl.textContent = "This is the only direct bus for the selected journey.";
  }

  renderInsights(c, alt);

  renderOutage(status.outage);

  loadForecast(bus.id, fromStop.id);
}

async function loadForecast(busId, stopId) {
  timeBarsEl.innerHTML = '<div class="empty empty-inline"><i class="bi bi-hourglass-split"></i>Loading\u2026</div>';
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
    timeBarsEl.innerHTML = `<div class="empty empty-inline"><i class="bi bi-plug"></i>Couldn't load forecast: ${esc(err)}</div>`;
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

  ctx.strokeStyle = "#262b34";
  ctx.fillStyle = "#8b93a1";
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
  ctx.fillStyle = "rgba(52,211,153,.10)";
  ctx.fill();

  ctx.beginPath();
  points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
  ctx.strokeStyle = "#34d399";
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = "#34d399";
  points.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#8b93a1";
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
      haptic([30, 60, 30], "heavy");
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
    lastKnownPosition = { latitude, longitude };
    myCoordsEl.textContent = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
    mySpeedEl.textContent = speed_kmh == null ? "\u2014" : `${speed_kmh.toFixed(1)} km/h`;
    updateUserMarker(latitude, longitude);
    lastKnownPosition = { latitude, longitude };
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
// Emergency & reporting: SOS/harassment, health emergency, bus issue
//
// These call new Tauri commands (submit_sos_report, submit_health_alert,
// report_bus_issue) that mirror the existing checkin_to_bus /
// submit_crowd_report commands. They need matching #[tauri::command]
// handlers added on the Rust side (see note below the file).
//
// The dedicated SOS page (setupSosPage and friends, below) sends four
// extra fields on submit_sos_report - contactName, contactPhone,
// photoFront, photoBack (the last two as JPEG data URLs) - so that
// handler's signature needs to grow to accept and persist them.
// Calling the trusted contact and taking the photos themselves are
// pure front-end/webview APIs (tel: links, getUserMedia) and need no
// native Rust command.
// ---------------------------------------------------------------------
function openModal(modalEl) {
  if (modalEl) modalEl.classList.add("open");
}
function closeModal(modalEl) {
  if (modalEl) modalEl.classList.remove("open");
}

function setupEmergencyFeatures() {
  healthBtnEl = document.getElementById("health-btn");
  breakdownBtnEl = document.getElementById("breakdown-btn");

  sosModalEl = document.getElementById("sos-modal");
  healthModalEl = document.getElementById("health-modal");
  breakdownModalEl = document.getElementById("breakdown-modal");

  sosOptionEls = document.querySelectorAll(".sos-option");
  sosDetailsEl = document.getElementById("sos-details");
  sosSubmitBtnEl = document.getElementById("sos-submit");
  sosStatusEl = document.getElementById("sos-status");

  healthAlertBtnEl = document.getElementById("health-alert-btn");

  breakdownBusEl = document.getElementById("breakdown-bus");
  breakdownNotesEl = document.getElementById("breakdown-notes");
  breakdownSubmitBtnEl = document.getElementById("breakdown-submit");
  breakdownStatusEl = document.getElementById("breakdown-status");

  // The panel's pulsing SOS button now opens the dedicated SOS page
  // (trusted contact + one-tap call/photo/report). Health emergency and
  // bus-issue reporting live on that same page (see index.html), still
  // wired to their modals here exactly as before.
  if (healthBtnEl) healthBtnEl.addEventListener("click", () => openModal(healthModalEl));
  if (breakdownBtnEl) {
    breakdownBtnEl.addEventListener("click", () => {
      populateBreakdownBusSelect();
      openModal(breakdownModalEl);
    });
  }

  // Close buttons + click-outside-to-close
  document.querySelectorAll(".modal-close").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(document.getElementById(btn.dataset.close)));
  });
  document.querySelectorAll(".modal-overlay").forEach((overlay) => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) overlay.classList.remove("open");
    });
  });

  // SOS type selection
  sosOptionEls.forEach((opt) => {
    opt.addEventListener("click", () => {
      sosOptionEls.forEach((o) => o.classList.remove("selected"));
      opt.classList.add("selected");
      selectedSosType = opt.dataset.type;
      sosSubmitBtnEl.disabled = false;
    });
  });

  if (sosSubmitBtnEl) sosSubmitBtnEl.addEventListener("click", submitSosReport);
  if (healthAlertBtnEl) healthAlertBtnEl.addEventListener("click", submitHealthAlert);
  if (breakdownSubmitBtnEl) breakdownSubmitBtnEl.addEventListener("click", submitBreakdownReport);

  setupSosPage();
}

// ---------------------------------------------------------------------
// Dedicated SOS page: trusted contact (called on SOS) + one-tap
// call + front/back photo capture + report submission.
// ---------------------------------------------------------------------
function setupSosPage() {
  trustedNameEl = document.getElementById("trusted-name");
  trustedPhoneEl = document.getElementById("trusted-phone");
  trustedContactTagEl = document.getElementById("trusted-contact-tag");
  trustedContactMsgEl = document.getElementById("trusted-contact-msg");
  pickContactBtnEl = document.getElementById("pick-contact-btn");
  saveContactBtnEl = document.getElementById("save-contact-btn");

  sosTriggerBtnEl = document.getElementById("sos-trigger-btn");
  sosTriggerTagEl = document.getElementById("sos-trigger-tag");
  sosTriggerStatusEl = document.getElementById("sos-trigger-status");
  sosOpenDetailedBtnEl = document.getElementById("sos-open-detailed-btn");

  cameraFlowEl = document.getElementById("camera-flow");
  cameraFlowLabelEl = document.getElementById("camera-flow-label");
  cameraFlowStatusEl = document.getElementById("camera-flow-status");
  cameraVideoEl = document.getElementById("camera-video");
  cameraCanvasEl = document.getElementById("camera-canvas");
  cameraSkipBtnEl = document.getElementById("camera-skip-btn");

  evidenceFrontEl = document.getElementById("evidence-front");
  evidenceBackEl = document.getElementById("evidence-back");

  if (!sosTriggerBtnEl) return; // page not present in this build

  loadTrustedContact();

  pickContactBtnEl?.addEventListener("click", pickTrustedContactFromPhone);
  saveContactBtnEl?.addEventListener("click", () => {
    saveTrustedContact(trustedNameEl.value.trim(), trustedPhoneEl.value.trim());
  });

  sosTriggerBtnEl.addEventListener("click", triggerSosAlert);
  sosOpenDetailedBtnEl?.addEventListener("click", () => openModal(sosModalEl));
  cameraSkipBtnEl?.addEventListener("click", () => {
    cameraSkipRequested = true;
  });
}

// ---- Trusted contact: load / save / pick from the phone's own contacts ----

function loadTrustedContact() {
  try {
    trustedContact = {
      name: localStorage.getItem("busmitra_trusted_name") || "",
      phone: localStorage.getItem("busmitra_trusted_phone") || "",
    };
  } catch {
    trustedContact = { name: "", phone: "" };
  }
  if (trustedNameEl) trustedNameEl.value = trustedContact.name;
  if (trustedPhoneEl) trustedPhoneEl.value = trustedContact.phone;
  renderTrustedContactTag();
}

function renderTrustedContactTag() {
  if (!trustedContactTagEl) return;
  if (trustedContact.phone) {
    trustedContactTagEl.textContent = `Calls ${trustedContact.name || trustedContact.phone}`;
    trustedContactTagEl.classList.add("set");
  } else if (DEFAULT_SOS_CONTACT.phone) {
    trustedContactTagEl.textContent = `Default: ${DEFAULT_SOS_CONTACT.name || "safety desk"}`;
    trustedContactTagEl.classList.add("set");
  } else {
    trustedContactTagEl.textContent = "Not set";
    trustedContactTagEl.classList.remove("set");
  }
}

function saveTrustedContact(name, phone) {
  trustedContact = { name, phone };
  try {
    localStorage.setItem("busmitra_trusted_name", name);
    localStorage.setItem("busmitra_trusted_phone", phone);
  } catch {
    // Private-browsing / storage-disabled: contact just won't persist
    // across restarts, but still works for this session.
  }
  renderTrustedContactTag();
  if (trustedContactMsgEl) {
    trustedContactMsgEl.textContent = phone ? "Saved on this phone." : "Cleared.";
  }
}

// Uses the device's own address book via the Contact Picker API, where
// the platform's webview supports it, so the person can choose someone
// already saved on their phone rather than retyping a number. Falls
// back to the manual fields (still saved to this device) everywhere else.
async function pickTrustedContactFromPhone() {
  if (!("contacts" in navigator) || !("ContactsManager" in window)) {
    trustedContactMsgEl.textContent =
      "Contact picker isn't available on this device \u2014 enter the number manually and tap Save.";
    return;
  }
  try {
    const [contact] = await navigator.contacts.select(["name", "tel"], { multiple: false });
    if (!contact) return;
    const name = contact.name?.[0] || "";
    const phone = contact.tel?.[0] || "";
    if (trustedNameEl) trustedNameEl.value = name;
    if (trustedPhoneEl) trustedPhoneEl.value = phone;
    saveTrustedContact(name, phone);
  } catch (err) {
    trustedContactMsgEl.textContent = `Couldn't read contacts (${err}) \u2014 enter the number manually.`;
  }
}

// ---- Front + back photo capture ----

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Opens one camera (front or back), shows a brief live preview so
// nothing is captured out of sight of whoever is holding the phone,
// then snapshots a frame and stops the stream. Returns a JPEG data URL,
// or null if the camera isn't available or the person skips.
async function captureOnePhoto(facingMode, label) {
  if (!navigator.mediaDevices?.getUserMedia) return null;
  if (cameraSkipRequested) return null;

  cameraFlowEl.hidden = false;
  cameraFlowLabelEl.textContent = label;
  cameraFlowStatusEl.textContent = "Starting camera\u2026";

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: facingMode } },
      audio: false,
    });
  } catch (err) {
    cameraFlowStatusEl.textContent = `Camera unavailable (${err.message || err})`;
    await wait(1000);
    cameraFlowEl.hidden = true;
    return null;
  }

  cameraVideoEl.srcObject = stream;
  try {
    await cameraVideoEl.play();
  } catch {
    // Autoplay can reject on some webviews even with muted+playsinline;
    // the stream still renders once metadata loads, so continue anyway.
  }

  cameraFlowStatusEl.textContent = "Hold steady\u2026";
  await wait(1200);

  if (cameraSkipRequested) {
    stream.getTracks().forEach((t) => t.stop());
    cameraFlowEl.hidden = true;
    return null;
  }

  const track = stream.getVideoTracks()[0];
  const settings = track.getSettings?.() || {};
  const w = settings.width || cameraVideoEl.videoWidth || 640;
  const h = settings.height || cameraVideoEl.videoHeight || 480;
  cameraCanvasEl.width = w;
  cameraCanvasEl.height = h;
  cameraCanvasEl.getContext("2d").drawImage(cameraVideoEl, 0, 0, w, h);
  const dataUrl = cameraCanvasEl.toDataURL("image/jpeg", 0.85);

  stream.getTracks().forEach((t) => t.stop());
  cameraFlowEl.hidden = true;
  return dataUrl;
}

function renderEvidenceThumb(which, dataUrl) {
  const slot = which === "front" ? evidenceFrontEl : evidenceBackEl;
  if (!slot) return;
  slot.innerHTML = `
    <img src="${dataUrl}" alt="${which === "front" ? "Front" : "Back"} evidence photo" />
    <button type="button" class="evidence-retake" data-retake="${which}">Retake</button>
  `;
  slot.querySelector(".evidence-retake").addEventListener("click", async () => {
    cameraSkipRequested = false;
    const facingMode = which === "front" ? "user" : "environment";
    const label = which === "front" ? "Front camera \u2014 face" : "Back camera \u2014 surroundings";
    const photo = await captureOnePhoto(facingMode, label);
    if (photo) {
      capturedPhotos[which] = photo;
      renderEvidenceThumb(which, photo);
    }
  });
}

// Captures a front photo (of whoever is holding the phone) followed by
// a back photo (of the surroundings), in sequence, so a single SOS tap
// leaves a visual record attached to the alert.
async function captureEvidencePhotos() {
  cameraSkipRequested = false;
  if (!navigator.mediaDevices?.getUserMedia) {
    sosTriggerStatusEl.textContent = "Camera access isn't available here \u2014 continuing without photos.";
    return;
  }
  const front = await captureOnePhoto("user", "Front camera \u2014 face");
  if (front) {
    capturedPhotos.front = front;
    renderEvidenceThumb("front", front);
  }
  if (cameraSkipRequested) return;
  const back = await captureOnePhoto("environment", "Back camera \u2014 surroundings");
  if (back) {
    capturedPhotos.back = back;
    renderEvidenceThumb("back", back);
  }
}

// ---- The SOS trigger itself: call + photos + report, in one tap ----

async function triggerSosAlert() {
  sosTriggerBtnEl.disabled = true;
  sosTriggerTagEl.textContent = "Working\u2026";
  sosTriggerTagEl.classList.add("busy");
  sosTriggerStatusEl.className = "sos-status";
  sosTriggerStatusEl.textContent = "Capturing evidence photos\u2026";

  await captureEvidencePhotos();

  sosTriggerStatusEl.textContent = "Sending alert\u2026";
  const contact = effectiveSosContact();
  try {
    const res = await invoke("submit_sos_report", {
      sosType: selectedSosType || "trigger",
      details: sosDetailsEl?.value || "",
      busId: selectedBusId,
      latitude: lastKnownPosition.latitude,
      longitude: lastKnownPosition.longitude,
      contactName: contact.name,
      contactPhone: contact.phone,
      photoFront: capturedPhotos.front,
      photoBack: capturedPhotos.back,
    });
    sosTriggerStatusEl.textContent = res?.message || "Alert sent \u2014 help has been notified.";
    // Green only if the contact was actually texted (or none was saved).
    const textFailed = Boolean(contact.phone) && res?.sms_status !== "sent";
    sosTriggerStatusEl.className = textFailed ? "sos-status err" : "sos-status ok";
  } catch (err) {
    sosTriggerStatusEl.textContent = `Couldn't send the report automatically (${err}) \u2014 the call below still goes through.`;
    sosTriggerStatusEl.className = "sos-status err";
  }

  // Browsers and mobile OSes never let a webpage silently place a call;
  // this opens the phone's own dialer with the number ready to go, one
  // tap away, rather than requiring the person to look up and type it.
  // Dial the saved trusted contact if there is one; otherwise fall back to
  // the national emergency number (112) so the button always leads to help.
  const hasContact = Boolean(contact.phone);
  const digits = hasContact
    ? contact.phone.replace(/[^\d+]/g, "")
    : EMERGENCY_FALLBACK_NUMBER;
  const telUrl = `tel:${digits}`;
  if (!hasContact) {
    sosTriggerStatusEl.textContent += ` No trusted contact saved \u2014 opening the dialer for ${EMERGENCY_FALLBACK_NUMBER}.`;
  } else if (contact.isDefault) {
    sosTriggerStatusEl.textContent += ` No trusted contact saved \u2014 alerting ${contact.name || "the safety desk"} instead.`;
  }
  try {
    // Tauri webviews often ignore tel: navigation, so hand it to the
    // OS through the opener plugin; fall back to plain navigation.
    const opener = window.__TAURI__?.opener;
    if (opener?.openUrl) await opener.openUrl(telUrl);
    else window.location.href = telUrl;
  } catch {
    window.location.href = telUrl;
  }

  sosTriggerTagEl.textContent = "Ready";
  sosTriggerTagEl.classList.remove("busy");
  sosTriggerBtnEl.disabled = false;
}

function populateBreakdownBusSelect() {
  if (!breakdownBusEl) return;
  const allBuses = [];
  for (const route of routes) {
    for (const bus of route.buses) {
      allBuses.push({ id: bus.id, label: `${route.route_number} \u2014 ${bus.bus_number}` });
    }
  }
  breakdownBusEl.innerHTML = allBuses
    .map((b) => `<option value="${b.id}">${b.label}</option>`)
    .join("");
  if (selectedBusId != null) breakdownBusEl.value = String(selectedBusId);
}

async function submitSosReport() {
  sosStatusEl.textContent = "Sending\u2026";
  sosStatusEl.className = "sos-status";
  try {
    const res = await invoke("submit_sos_report", {
      sosType: selectedSosType,
      details: sosDetailsEl.value,
      busId: selectedBusId,
      latitude: lastKnownPosition.latitude,
      longitude: lastKnownPosition.longitude,
    });
    sosStatusEl.textContent = res?.message || "Report sent. Stay safe \u2014 help has been notified.";
    sosStatusEl.className = "sos-status ok";
  } catch (err) {
    sosStatusEl.textContent = `Couldn't send automatically (${err}) \u2014 please use the call buttons above.`;
    sosStatusEl.className = "sos-status err";
  }
}

async function submitHealthAlert() {
  const originalText = healthAlertBtnEl.textContent;
  healthAlertBtnEl.disabled = true;
  healthAlertBtnEl.textContent = "Alerting\u2026";
  try {
    const res = await invoke("submit_health_alert", {
      busId: selectedBusId,
      latitude: lastKnownPosition.latitude,
      longitude: lastKnownPosition.longitude,
    });
    healthAlertBtnEl.textContent = res?.message || "Driver alerted";
  } catch (err) {
    healthAlertBtnEl.textContent = "Alert failed \u2014 call 108 directly";
  } finally {
    setTimeout(() => {
      healthAlertBtnEl.disabled = false;
      healthAlertBtnEl.textContent = originalText;
    }, 3000);
  }
}

async function submitBreakdownReport() {
  breakdownStatusEl.textContent = "Submitting\u2026";
  breakdownStatusEl.className = "sos-status";
  const busId = Number(breakdownBusEl.value);
  const issueType = document.querySelector('input[name="breakdown-type"]:checked')?.value || "other";
  try {
    const res = await invoke("report_bus_issue", {
      busId,
      issueType,
      notes: breakdownNotesEl.value,
    });
    breakdownStatusEl.textContent = res?.message || "Thanks \u2014 this has been flagged.";
    breakdownStatusEl.className = "sos-status ok";
  } catch (err) {
    breakdownStatusEl.textContent = `Failed to submit (${err}) \u2014 try again.`;
    breakdownStatusEl.className = "sos-status err";
  }
}

// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  fromEl = document.getElementById("from");
  toEl = document.getElementById("to");
  predictBtn = document.getElementById("predict");
  swapBtnEl = document.getElementById("swap-btn");
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
  insightsBodyEl = document.getElementById("insights-body");
  insightsTagEl = document.getElementById("insights-tag");
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
  weatherChipEl = document.getElementById("weather-chip");
  weatherIconEl = document.getElementById("weather-icon");
  weatherTextEl = document.getElementById("weather-text");
  weatherAdvisoryEl = document.getElementById("weather-advisory");
  weatherAdvisoryTextEl = document.getElementById("weather-advisory-text");
  outageTagEl = document.getElementById("outage-tag");
  outageBannerEl = document.getElementById("outage-banner");
  outageReasonEl = document.getElementById("outage-reason");
  outageReportBtnEl = document.getElementById("outage-report-btn");
  outageMsgEl = document.getElementById("outage-msg");

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

  // Reversing a journey shouldn't mean reopening both dropdowns from
  // scratch. Swaps the two select values directly; the existing "from
  // changed" listener above already keeps from/to from colliding.
  swapBtnEl?.addEventListener("click", () => {
    const a = fromEl.value;
    fromEl.value = toEl.value;
    toEl.value = a;
    swapBtnEl.classList.toggle("swapped");
    haptic();
  });

  setupOnboardingTip();

  boardStopEl.addEventListener("change", loadBoard);
  boardIncludeEl.addEventListener("change", loadBoard);

  addBusBtnEl.addEventListener("click", doAddBus);
  demoToggleEl.addEventListener("click", toggleDemo);
  demoResetEl.addEventListener("click", resetDemo);
  outageReportBtnEl.addEventListener("click", doOutageReport);

  // Held in memory only - never persisted, so closing the app forgets it.
  adminTokenEl.addEventListener("input", () => {
    adminToken = adminTokenEl.value;
  });

  setupNavigation();
  initMap();
  setupTracking();
  setupPlanner();
  setupEmergencyFeatures();
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
    loadWeather();
  });
  // Start location tracking automatically on app startup instead of
  // waiting for the user to click "Enable live tracking".
  startTracking();
});