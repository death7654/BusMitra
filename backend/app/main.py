import asyncio
import socket

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from .routers import crowd
from .database import Base, engine, ensure_schema, get_db
from .schemas import HealthResponse
from .routers import tracking
from .routers import bus
from .routers import prediction
from .routers import routes as routes_router
from .routers import admin as admin_router
from .routers import demo as demo_router
from .routers import arrivals as arrivals_router
from .routers import model as model_router
from .routers import stream as stream_router
from .routers import fleet_status as fleet_status_router
from .routers import journeys as journeys_router
from .routers import calibration as calibration_router
from .routers import outage as outage_router
from .routers import weather as weather_router
from .routers import tiles as tiles_router
from .services import demo as demo_service
from .services import learning as learning_service
from .services import observations as observation_service
from .services.crowd_aggregation import auto_checkout_stale_sessions

# Create database tables
Base.metadata.create_all(bind=engine)

# Add any columns introduced after the database file was first created.
# create_all won't do this for an existing table, so without it an old
# data/bus.db would break the moment a query touches a new column.
_migrations = ensure_schema()


# Create FastAPI application
app = FastAPI(
    title="Bus Crowd Intelligence API",
    description=(
        "Backend API for bus tracking, crowd monitoring, "
        "and bus fullness prediction."
    ),
    version="0.2.0",
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_lan_ip() -> str:
    """Best-effort LAN IP this machine is reachable at from other devices
    on the same network (e.g. an Android phone/emulator). Doesn't send
    any real traffic — just asks the OS which local interface it would
    use to reach an external address.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@app.on_event("startup")
def log_lan_ip():
    ip = get_lan_ip()
    print(f"\nBackend reachable on your network at: http://{ip}:8000")
    print(f"Point the client's base URL at that address if it doesn't match.\n")

    if _migrations:
        print(f"Applied schema migrations: {', '.join(_migrations)}")


@app.on_event("startup")
def close_stale_rides():
    """
    Close check-ins left open by a previous run.

    Open check-ins deliberately don't expire on a timer, so without
    this a phone that died mid-journey last week would still be
    counted as a passenger today.
    """

    from .database import SessionLocal

    db = SessionLocal()

    try:
        closed = auto_checkout_stale_sessions(db)

        if closed:
            print(f"Auto-closed {closed} stale check-in(s).")
    finally:
        db.close()


# ---------------------------------------------------------
# Observation sampler
# ---------------------------------------------------------
#
# The model ships trained on synthetic data. This task is what lets it
# stop being synthetic: every couple of minutes it writes down what the
# live signals actually measured, and ml/train.py folds those rows in
# on the next run.
#
# It only records measurements with real evidence behind them - see
# services/observations.py for why logging everything would teach the
# model that the entire fleet runs empty.

_sampler_task: asyncio.Task | None = None


async def _sample_observations_forever():
    from .database import SessionLocal

    while True:
        await asyncio.sleep(
            observation_service.SAMPLE_INTERVAL_SECONDS
        )

        db = SessionLocal()

        try:
            # Snapshots taken while the simulator is running are
            # tagged, not skipped: the demo should visibly exercise the
            # learning loop, and training excludes them by default.
            await asyncio.to_thread(
                observation_service.sample_fleet,
                db,
                demo_service.simulator.running,
            )
        except Exception as exc:
            # A sampling failure must never take the API down with it.
            # This is a background nicety; serving requests is not.
            print(f"Observation sampling failed: {exc}")
            db.rollback()
        finally:
            db.close()


# ---------------------------------------------------------
# Learning loop
# ---------------------------------------------------------
#
# Separate from the observation sampler because it does a different
# job on a different clock. The sampler records what the fleet looks
# like *now*; this looks back over what already happened and turns it
# into the three things that make future answers better: learned
# traffic speeds per segment, scored predictions, and reporter trust.
#
# It runs less often than the sampler on purpose. Each pass walks the
# whole fleet's recent tracks, and none of what it produces changes
# meaningfully minute to minute.

LEARNING_INTERVAL_SECONDS = 120

_learning_task: asyncio.Task | None = None


async def _learn_forever():
    from .database import SessionLocal

    while True:
        await asyncio.sleep(LEARNING_INTERVAL_SECONDS)

        db = SessionLocal()

        try:
            summary = await asyncio.to_thread(
                learning_service.run_once,
                db,
                demo_service.simulator.running,
            )

            failures = {
                stage: result["error"]
                for stage, result in summary.items()
                if isinstance(result, dict) and "error" in result
            }

            if failures:
                print(f"Learning pass had failures: {failures}")
        except Exception as exc:
            # Same contract as the sampler: this is an improvement
            # loop, not a serving path. It must never take the API
            # down with it.
            print(f"Learning pass failed: {exc}")
            db.rollback()
        finally:
            db.close()


@app.on_event("startup")
async def start_observation_sampler():
    global _sampler_task

    _sampler_task = asyncio.create_task(_sample_observations_forever())


@app.on_event("startup")
async def start_learning_loop():
    global _learning_task

    _learning_task = asyncio.create_task(_learn_forever())


@app.on_event("shutdown")
async def stop_observation_sampler():
    if _sampler_task is not None:
        _sampler_task.cancel()


@app.on_event("shutdown")
async def stop_learning_loop():
    if _learning_task is not None:
        _learning_task.cancel()


@app.on_event("shutdown")
async def stop_demo_simulation():
    """
    Never leave generated data behind on shutdown - a stopped server
    can't tell anyone its numbers were fake.
    """

    if demo_service.simulator.running:
        await demo_service.simulator.stop(purge=True)


# Register routers
app.include_router(tracking.router)
app.include_router(tiles_router.router)

@app.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """
    Check whether the API and database are working.
    """

    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "database": "connected",
            "demo_mode": demo_service.simulator.running,
        }

    except Exception:
        return {
            "status": "ok",
            "database": "error",
            "demo_mode": demo_service.simulator.running,
        }

app.include_router(crowd.router)
app.include_router(bus.router)
app.include_router(prediction.router)
app.include_router(routes_router.router)
app.include_router(admin_router.router)
app.include_router(demo_router.router)
app.include_router(arrivals_router.router)
app.include_router(model_router.router)

# Added alongside the per-bus endpoints rather than replacing them.
# The batch call is an optimisation the client uses when it can, and
# the single-bus calls remain the fallback when it can't.
app.include_router(fleet_status_router.router)
app.include_router(stream_router.router)
app.include_router(journeys_router.router)
app.include_router(calibration_router.router)
app.include_router(outage_router.router)
app.include_router(weather_router.router)
