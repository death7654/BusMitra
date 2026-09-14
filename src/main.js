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
function bandColor(pct) {
  if (pct > 80) return "var(--red)";
  if (pct >= 50) return "var(--yellow)";
  return "var(--green)";
}

// ---------------------------------------------------------------------
// State
// ---------------------------------------------------------------------
let routes = [];        // from get_routes
let candidates = [];    // computed per Predict click
let selectedBusId = null;
let trackingStarted = false;
let lastNotifiedStatus = new Map(); // bus_id -> last status we already notified about

// DOM refs (filled in on DOMContentLoaded)
let fromEl, toEl, predictBtn, noticeEl, countEl, busListEl;
let selectedTagEl, gaugeEl, gaugePctEl, levelEl, detailEl, nextEl, nextEtaEl;
let recommendTextEl, historyTagEl, timeBarsEl, daysEl;
let forecastTagEl, chartEl, patternEl, betterEl;
let myCoordsEl, mySpeedEl, myMatchWrapEl, trackBtnEl;
let onlineDotEl, onlineTextEl;
let liveMapEl, mapTagEl;

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
  marker.setPopupContent(`<b>${status.bus_number}</b><br>${Math.round(status.overall_fullness)}% full`);
  if (!marker.getPopup()) marker.bindPopup(`<b>${status.bus_number}</b><br>${Math.round(status.overall_fullness)}% full`);
}

// Keep every bus on the map moving, not just the ones from the last
// search. Polls all known bus ids on a fixed interval for as long as
// the app is open.
let busPollTimer = null;
async function pollAllBuses() {
  const busIds = new Set();
  for (const route of routes) {
    for (const bus of route.buses) busIds.add(bus.id);
  }
  await Promise.all(
    [...busIds].map(async (busId) => {
      try {
        const status = await invoke("get_bus_status", { busId });
        updateBusMarker(status);
      } catch {
        // A single bus failing to report shouldn't stop the others.
      }
    })
  );
}
function startBusPolling(intervalMs = 8000) {
  if (busPollTimer) return;
  pollAllBuses();
  busPollTimer = setInterval(pollAllBuses, intervalMs);
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
// Real ETA: derived from the bus's live GPS distance to the boarding
// stop (haversine, above) and its latest reported ground speed
// (BusStatusResponse.latest_speed, km/h, from the matched rider's GPS
// ping). No made-up numbers: if we don't have both a live distance and
// a live, moving speed reading, we say so instead of guessing.
// ---------------------------------------------------------------------
function estimateETA(meters, speedKmh) {
  if (meters == null) return null; // no live GPS fix on this bus yet
  if (meters < 60) return "Arriving now";
  if (speedKmh == null || speedKmh < 1) return null; // no reliable speed reading

  const speedMetersPerMin = (speedKmh * 1000) / 60;
  const minutes = meters / speedMetersPerMin;

  if (minutes < 1) return "<1 min";
  if (minutes < 60) return `~${Math.round(minutes)} min`;

  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return `~${hours}h ${mins}m`;
}

// ---------------------------------------------------------------------
// Backend data loading
// ---------------------------------------------------------------------
async function loadRoutes() {
  try {
    routes = await invoke("get_routes");
    onlineDotEl.classList.remove("offline");
    onlineTextEl.textContent = "Prediction engine online";
    populateStopSelects();
    fitMapToStops();
    startBusPolling();
  } catch (err) {
    onlineDotEl.classList.add("offline");
    onlineTextEl.textContent = "Backend unreachable";
    busListEl.innerHTML = `<div class="empty">Can't reach the backend (${err}). Check that uvicorn is running.</div>`;
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
  const optionsHtml = names.map((n) => `<option value="${n}">${n}</option>`).join("");
  fromEl.innerHTML = optionsHtml;
  toEl.innerHTML = optionsHtml;
  if (names.length > 1) {
    fromEl.value = names[0];
    toEl.value = names[1];
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

  const results = await Promise.all(
    found.map(async (c) => {
      try {
        const [status, prediction] = await Promise.all([
          invoke("get_bus_status", { busId: c.bus.id }),
          invoke("get_bus_prediction", { busId: c.bus.id, stopId: c.fromStop.id }),
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
        return { ...c, status, prediction, distance, error: null };
      } catch (err) {
        return { ...c, status: null, prediction: null, distance: null, error: String(err) };
      }
    })
  );

  results.sort((a, b) => {
    if (a.distance == null && b.distance == null) return 0;
    if (a.distance == null) return 1;
    if (b.distance == null) return -1;
    return a.distance - b.distance;
  });

  candidates = results;
  selectedBusId = candidates.find((c) => !c.error)?.bus.id ?? null;

  const okCount = candidates.filter((c) => !c.error).length;
  noticeEl.classList.remove("show");
  if (okCount > 0) {
    const best = candidates.find((c) => !c.error);
    noticeEl.textContent = `${okCount} direct bus${okCount > 1 ? "es" : ""} found. Lowest predicted crowd: ${best.bus.bus_number} at ${Math.round(best.prediction.final_fullness)}%.`;
    noticeEl.classList.add("good", "show");
  }

  predictBtn.disabled = false;
  predictBtn.textContent = "Predict buses \u2192";

  renderList();
  renderSelected();
}

// ---------------------------------------------------------------------
// Rendering: bus list
// ---------------------------------------------------------------------
function renderList() {
  countEl.textContent = candidates.filter((c) => !c.error).length;

  if (candidates.length === 0) return;

  busListEl.innerHTML = candidates
    .map((c) => {
      const open = selectedBusId === c.bus.id;
      if (c.error) {
        return `<div class="bus" data-id="${c.bus.id}">
          <div class="bus-head"><div class="route"><div class="number">${c.route.route_number}</div><div class="route-name">${c.bus.bus_number}</div></div></div>
          <div class="bus-meta"><span style="color:var(--red);font-size:11px">Couldn't load this bus (${c.error})</span></div>
        </div>`;
      }
      const pct = Math.round(c.prediction.final_fullness);
      const color = colorFor(c.prediction.status);
      const distanceLabel = formatDistance(c.distance) || "No live GPS yet";
      const etaLabel = estimateETA(c.distance, c.status.latest_speed);
      const etaMain = etaLabel || distanceLabel;
      const etaSub = etaLabel
        ? `${distanceLabel} \u00b7 ${c.fromStop.name}`
        : c.fromStop.name;
      const primaryBus = c.route.buses.find((b) => b.id === Math.min(...c.route.buses.map((x) => x.id)));
      const liveTag = c.isPrimary
        ? `<span class="factor">Live GPS matched</span>`
        : `<span class="no-live-tag">Prediction only (this route's live GPS goes to ${primaryBus.bus_number})</span>`;

      return `<div class="bus ${open ? "selected" : ""}" data-id="${c.bus.id}">
        <div class="bus-head">
          <div class="route"><div class="number">${c.route.route_number}</div><div class="route-name">${c.bus.bus_number}</div></div>
          <div class="eta">${etaMain}<span>${etaSub}</span></div>
        </div>
        <div class="bus-meta">
          <div class="mini-bar"><div class="fill" style="width:${Math.min(100, pct)}%;background:${color}"></div></div>
          <div class="status" style="color:${color}">${c.prediction.status}</div>
          <div class="confidence">${c.status.active_passengers} live rider${c.status.active_passengers === 1 ? "" : "s"} &middot; ${c.status.report_count} report${c.status.report_count === 1 ? "" : "s"}</div>
        </div>
        <div class="expand">
          <div class="factors">${liveTag}<span class="factor">${c.route.route_name}</span></div>
          <div class="bus-actions">
            <button class="action-btn" data-checkin="${c.bus.id}">Check in to this bus</button>
          </div>
          <div class="report-row">
            <select data-crowd-select="${c.bus.id}">
              <option value="1">1 - Very low</option>
              <option value="2">2 - Low</option>
              <option value="3" selected>3 - Moderate</option>
              <option value="4">4 - High</option>
              <option value="5">5 - Very high</option>
            </select>
            <button class="action-btn" data-report="${c.bus.id}">Submit crowd report</button>
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
  busListEl.querySelectorAll("[data-report]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const busId = Number(btn.dataset.report);
      const select = busListEl.querySelector(`[data-crowd-select="${busId}"]`);
      doReport(busId, Number(select.value));
    });
  });
}

async function doCheckIn(busId) {
  const msgEl = document.getElementById(`action-msg-${busId}`);
  try {
    const res = await invoke("checkin_to_bus", { busId });
    msgEl.textContent = res.message;
  } catch (err) {
    msgEl.textContent = `Check-in failed: ${err}`;
  }
}

async function doReport(busId, crowdLevel) {
  const msgEl = document.getElementById(`action-msg-${busId}`);
  try {
    const res = await invoke("submit_crowd_report", { busId, crowdLevel });
    msgEl.textContent = res.message;
    // Refresh this candidate's numbers so the list/gauge reflect the new report.
    const c = candidates.find((x) => x.bus.id === busId);
    if (c) {
      const [status, prediction] = await Promise.all([
        invoke("get_bus_status", { busId }),
        invoke("get_bus_prediction", { busId, stopId: c.fromStop.id }),
      ]);
      c.status = status;
      c.prediction = prediction;
      renderList();
      if (selectedBusId === busId) renderSelected();
    }
  } catch (err) {
    msgEl.textContent = `Report failed: ${err}`;
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
  recommendTextEl.textContent = "Pick a route to see the best travel option.";
  patternEl.textContent = "Select a route to see how its number is calculated.";
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

  const distanceLabel = formatDistance(c.distance);
  nextEl.textContent = distanceLabel || "No live GPS yet";

  const etaLabel = estimateETA(c.distance, status.latest_speed);
  nextEtaEl.textContent =
    etaLabel ||
    (c.distance == null
      ? "No live GPS yet"
      : "Bus speed unavailable");

  patternEl.textContent = `Live: ${Math.round(status.passenger_fullness)}% from ${status.active_passengers} active rider${status.active_passengers === 1 ? "" : "s"}${status.manual_fullness != null ? ` and ${Math.round(status.manual_fullness)}% from ${status.report_count} manual report${status.report_count === 1 ? "" : "s"}` : ""}, blended 60/40 with a ${Math.round(prediction.predicted_fullness)}% ML forecast.`;

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
    timeBarsEl.innerHTML = `<div class="empty" style="padding:10px">Couldn't load forecast: ${err}</div>`;
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
  myMatchWrapEl.innerHTML = `<div class="match-pill">On ${status.bus_number} &middot; ${pct}% full</div>`;
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
  myCoordsEl = document.getElementById("my-coords");
  mySpeedEl = document.getElementById("my-speed");
  myMatchWrapEl = document.getElementById("my-match-wrap");
  trackBtnEl = document.getElementById("track-btn");
  onlineDotEl = document.getElementById("online-dot");
  onlineTextEl = document.getElementById("online-text");
  liveMapEl = document.getElementById("live-map");
  mapTagEl = document.getElementById("map-tag");

  fromEl.addEventListener("change", () => {
    if (fromEl.value === toEl.value) {
      const opt = [...toEl.options].find((o) => o.value !== fromEl.value);
      if (opt) toEl.value = opt.value;
    }
  });

  predictBtn.addEventListener("click", runPredict);

  initMap();
  setupTracking();
  loadRoutes();
  resetSelectedPanels();
  // Start location tracking automatically on app startup instead of
  // waiting for the user to click "Enable live tracking".
  startTracking();
});