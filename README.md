# BusMitra

**Real-time bus tracking and crowd prediction**, built as a cross-platform Tauri app (desktop + Android) backed by a Python/FastAPI service with a machine-learning crowd predictor.

Riders share anonymous GPS pings, manual check-ins, and crowd reports. BusMitra matches them to a live bus, combines that with a Random Forest prediction trained on historical fullness data, and tells the rider whether to leave now, wait, or catch the next one.

> Built for **Technova 2026** by team **MetroMotion**.

---

## How it works

```text
Rider's phone / desktop (Tauri app)
        │
        ├── GPS ping ─────────┐
        ├── Manual check-in   │
        └── Crowd report      │
                               ▼
                     FastAPI backend (Python)
                               │
                ┌──────────────┼───────────────┐
                ▼              ▼               ▼
          Bus matching   Crowd aggregation   ML prediction
          (GPS distance) (live passengers)   (Random Forest)
                │              │               │
                └──────────────┼───────────────┘
                               ▼
                     Final fullness + recommendation
                               │
                               ▼
                 Pushed back to the app as live events
```

The Rust side of the Tauri app owns geolocation, talks to the backend over HTTP, and re-emits everything as Tauri events (`location-update`, `ping-update`, `bus-status-update`) that the frontend listens for — no polling from JS.

---

## Tech stack

| Layer | Technology |
|---|---|
| App shell | [Tauri 2](https://tauri.app) (Rust core + system webview) |
| Frontend | Vanilla HTML/CSS/JS |
| Native plugins | `tauri-plugin-geolocation`, `tauri-plugin-http`, `tauri-plugin-notification`, `tauri-plugin-opener` |
| Backend | FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy |
| ML | scikit-learn `RandomForestRegressor`, pandas, NumPy, joblib |
| Testing | pytest + HTTPX |

---

## Project structure

```text
BusMitra/
│
├── src/                      # Frontend (vanilla JS, loaded into the Tauri webview)
│   ├── index.html
│   ├── main.js                # Tauri invoke calls + event listeners
│   ├── styles.css
│   └── assets/
│
├── src-tauri/                 # Tauri/Rust app shell
│   ├── src/
│   │   ├── lib.rs             # Tauri commands: tracking, check-in, reports, predictions
│   │   └── main.rs
│   ├── capabilities/          # Permission manifests (geolocation, http, notification)
│   ├── icons/                 # App icons (desktop, Windows, iOS, Android)
│   ├── gen/android/           # Generated Android Studio/Gradle project (build output)
│   ├── Cargo.toml
│   └── tauri.conf.json        # App identifier: com.robin.BusMitra
│
├── backend/                   # FastAPI service (see backend/README.md for full docs)
│   ├── app/
│   │   ├── main.py            # FastAPI app entrypoint
│   │   ├── database.py        # SQLite + SQLAlchemy setup
│   │   ├── models.py          # Route, Bus, BusStop, UserPing, CheckIn, CrowdReport
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── seed.py            # Demo data seeding
│   │   ├── routers/           # tracking, crowd, bus, prediction endpoints
│   │   └── services/          # GPS matching, crowd aggregation, prediction logic
│   ├── ml/
│   │   ├── train.py           # Trains the Random Forest model
│   │   └── model.joblib       # Trained model artifact
│   ├── data/
│   │   ├── bus.db             # SQLite database
│   │   └── historical_fullness.csv
│   ├── tests/
│   ├── requirements.txt
│   ├── launch.ps1             # One-shot Windows script: install → seed → train → run
│   └── README.md              # Full backend API reference
│
├── package.json
└── LICENSE                    # AGPL-3.0
```

---

## Getting started

### Prerequisites

- [Node.js](https://nodejs.org/) + npm
- [Rust](https://www.rust-lang.org/tools/install) toolchain
- [Tauri prerequisites](https://tauri.app/start/prerequisites/) for your OS
- Python 3.10+ (for the backend)
- For Android builds: Android Studio, Android SDK/NDK ([Tauri Android setup](https://tauri.app/distribute/android/))

### 1. Start the backend

```bash
cd backend
pip install -r requirements.txt
python -m app.seed        # populate demo routes/buses/stops
python ml/train.py        # train the Random Forest model
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Or, on Windows, run the whole sequence in one step:

```powershell
cd backend
./launch.ps1
```

Swagger docs: `http://127.0.0.1:8000/docs` — full API reference in [`backend/README.md`](backend/README.md).

### 2. Install frontend dependencies

```bash
npm install
```

### 3. Run the app

```bash
npm run tauri dev        # desktop
npm run tauri android dev  # Android (emulator or connected device)
```

### Backend URL by target

`src-tauri/src/lib.rs` hardcodes the backend base URL — update it for your setup:

| Target | Backend URL |
|---|---|
| Desktop (Windows/macOS/Linux) | `http://127.0.0.1:8000` |
| Android emulator | `http://10.0.2.2:8000` (emulator's alias for the host loopback) |
| Physical Android device | `http://<your-LAN-IP>:8000`, phone and machine on the same network |

---

## Building for release

```bash
npm run tauri build           # desktop installers
npm run tauri android build   # signed Android APK/AAB
```

---

## License

AGPL-3.0 — see [LICENSE](LICENSE).

## Team — BusMitra @ Technova 2026

- Dhanush Subhash
- Flavia Dary Joseph
- Robinson George Arysseril
- Rosmi Reji
- Tessa Mariya
