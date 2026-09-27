"""
Demo mode: a background simulation that drives the fleet.

The app is only interesting when buses are moving and riders are on
board, and neither happens on a laptop with no GPS and no passengers.
Rather than faking numbers in the UI - where they'd quietly diverge
from what the backend believes - this writes ordinary UserPing and
CrowdReport rows to the same tables real riders write to. Every
endpoint downstream (status, prediction, map, forecast) then works
without knowing demo mode exists.

Two rules keep that honest:

  * Demo rows are tagged by user_id (see DEMO_USER_ID_BASE) so they
    can always be told apart from real data and removed completely.
  * Demo mode is off by default and reports itself loudly through
    /api/demo/status and /health, so nobody mistakes a simulated
    crowd for a real one.
"""

import asyncio
import math
import os
import random
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Bus, CheckIn, CrowdObservation, CrowdReport, UserPing
from .crowd_aggregation import CROWD_LEVEL_TO_PERCENTAGE


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

# Real user ids are generated from a nanosecond clock modulo 1e9, so
# they never exceed 1_000_000_000. Starting demo ids above that leaves
# no chance of a simulated rider colliding with a real device.
DEMO_USER_ID_BASE = 2_000_000_000

# Seconds between simulation steps.
TICK_SECONDS = float(os.environ.get("BUSMITRA_DEMO_TICK_SECONDS", "5"))

# Simulated ground speed. This is the speed actually used to advance
# each bus along its route *and* the speed reported on the pings, so
# the ETAs the UI derives from it are internally consistent.
SPEED_KMH = float(os.environ.get("BUSMITRA_DEMO_SPEED_KMH", "32"))

# Demo mode can be switched off entirely (e.g. on a shared server)
# without touching the code.
ENABLED = os.environ.get("BUSMITRA_DEMO_ENABLED", "1") not in (
    "0",
    "false",
    "False",
    "",
)

# Simulated pings older than this are pruned every tick. The crowd
# aggregation only looks back 5 minutes, so anything older is dead
# weight that would grow the SQLite file for the length of the demo.
PING_RETENTION_MINUTES = 12

# One in N ticks a simulated rider files a manual crowd report.
REPORT_EVERY_N_TICKS = 6


def is_demo_user_id(user_id: int) -> bool:
    return user_id >= DEMO_USER_ID_BASE


# Serialises everything that writes or deletes demo rows.
#
# Cancelling the simulation task doesn't stop the worker thread it
# handed a tick to - asyncio.to_thread has no way to interrupt it - so
# stop(purge=True) could otherwise delete the simulated rows and then
# have that in-flight tick insert a fresh batch a moment later, leaving
# generated data behind after the UI said it was cleared.
_db_lock = threading.Lock()


# ---------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------

def _haversine_meters(lat1, lon1, lat2, lon2) -> float:
    radius = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )

    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class _Path:
    """A route's stops as a polyline that can be sampled by distance."""

    def __init__(self, points: list[tuple[float, float]]):
        self.points = points
        self.segments: list[float] = []

        for i in range(len(points) - 1):
            self.segments.append(
                _haversine_meters(
                    points[i][0],
                    points[i][1],
                    points[i + 1][0],
                    points[i + 1][1],
                )
            )

        self.length = sum(self.segments)

    def position_at(self, distance: float) -> tuple[float, float]:
        """Interpolate a lat/lon this far along the polyline."""

        if self.length <= 0:
            return self.points[0]

        distance = max(0.0, min(distance, self.length))
        travelled = 0.0

        for i, seg_length in enumerate(self.segments):
            if seg_length <= 0:
                continue

            if travelled + seg_length >= distance:
                ratio = (distance - travelled) / seg_length
                lat1, lon1 = self.points[i]
                lat2, lon2 = self.points[i + 1]

                return (
                    lat1 + (lat2 - lat1) * ratio,
                    lon1 + (lon2 - lon1) * ratio,
                )

            travelled += seg_length

        return self.points[-1]


# ---------------------------------------------------------
# Per-bus simulation state
# ---------------------------------------------------------

class _SimulatedBus:
    def __init__(self, bus: Bus, path: _Path, index: int):
        self.bus_id = bus.id
        self.bus_number = bus.bus_number
        self.capacity = bus.capacity
        self.path = path

        # Spread the fleet out along the route instead of stacking
        # every bus on the first stop.
        self.distance = (path.length / max(1, index + 1)) * 0.5
        self.direction = 1 if index % 2 == 0 else -1

        # Each bus gets its own phase so they don't all fill and empty
        # in lockstep, which looks obviously fake on the map.
        self.phase = random.uniform(0, math.tau)

        self.latitude, self.longitude = path.position_at(self.distance)
        self.riders = 0

    def advance(self, meters: float) -> None:
        self.distance += meters * self.direction

        # Bounce off the ends of the route rather than teleporting
        # back to the start - a bus that jumps across the city breaks
        # the ETA maths for anyone watching it.
        if self.distance >= self.path.length:
            self.distance = self.path.length
            self.direction = -1
        elif self.distance <= 0:
            self.distance = 0.0
            self.direction = 1

        self.latitude, self.longitude = self.path.position_at(
            self.distance
        )

    def target_riders(self, now: datetime) -> int:
        """
        A plausible passenger load for this moment.

        Three overlapping terms: a low overnight baseline, a broad
        daytime plateau, and two sharp commuter peaks around 9am and
        6pm. Without the plateau the model made 1pm as empty as 3am,
        which is wrong for a city route and made daytime demos look
        broken. Offset per bus, plus noise so consecutive ticks don't
        trace a suspiciously smooth curve.
        """

        hour = now.hour + now.minute / 60.0

        daytime = math.exp(-(((hour - 14.0) / 6.0) ** 2))
        morning = math.exp(-(((hour - 9.0) / 2.6) ** 2))
        evening = math.exp(-(((hour - 18.0) / 2.6) ** 2))

        load = (
            0.12
            + 0.30 * daytime
            + 0.50 * max(morning, evening)
        )
        load *= 0.85 + 0.15 * math.sin(self.phase)
        load += random.uniform(-0.06, 0.06)

        load = max(0.05, min(0.98, load))

        return max(1, int(round(self.capacity * load)))


# ---------------------------------------------------------
# Simulator
# ---------------------------------------------------------

class DemoSimulator:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._buses: list[_SimulatedBus] = []
        self._lock = asyncio.Lock()

        self.running = False
        self.started_at: datetime | None = None
        self.ticks = 0

    # -----------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------

    async def start(self) -> None:
        async with self._lock:
            if self.running:
                return

            self._buses = await asyncio.to_thread(self._build_fleet)

            if not self._buses:
                raise RuntimeError(
                    "No buses with usable route stops were found. "
                    "Seed the database first (python -m app.seed)."
                )

            self.running = True
            self.started_at = datetime.utcnow()
            self.ticks = 0
            self._task = asyncio.create_task(self._loop())

    async def stop(self, purge: bool = False) -> int:
        async with self._lock:
            self.running = False

            if self._task is not None:
                self._task.cancel()

                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass

                self._task = None

            self._buses = []

        if purge:
            counts = await asyncio.to_thread(purge_demo_data)
            return sum(counts.values())

        return 0

    # -----------------------------------------------------
    # Main loop
    # -----------------------------------------------------

    async def _loop(self) -> None:
        meters_per_tick = (SPEED_KMH * 1000 / 3600) * TICK_SECONDS

        while self.running:
            try:
                for sim in self._buses:
                    sim.advance(meters_per_tick)

                await asyncio.to_thread(self._write_tick)
                self.ticks += 1

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # One bad tick shouldn't kill the simulation; the next
                # one may well succeed (e.g. a transient SQLite lock).
                print(f"[demo] tick failed: {exc}")

            await asyncio.sleep(TICK_SECONDS)

    # -----------------------------------------------------
    # Database work (always called via asyncio.to_thread, since
    # SQLAlchemy's sync session would otherwise block the event loop)
    # -----------------------------------------------------

    def _build_fleet(self) -> list[_SimulatedBus]:
        db: Session = SessionLocal()

        try:
            simulated: list[_SimulatedBus] = []

            buses = db.query(Bus).order_by(Bus.id).all()

            for index, bus in enumerate(buses):
                stops = sorted(bus.route.bus_stops, key=lambda s: s.id)

                # A single stop isn't a path - there's nowhere to drive.
                if len(stops) < 2:
                    continue

                path = _Path(
                    [(stop.latitude, stop.longitude) for stop in stops]
                )

                if path.length <= 0:
                    continue

                simulated.append(_SimulatedBus(bus, path, index))

            return simulated

        finally:
            db.close()

    def _write_tick(self) -> None:
        with _db_lock:
            self._write_tick_locked()

    def _write_tick_locked(self) -> None:
        db: Session = SessionLocal()
        now = datetime.utcnow()

        try:
            for sim in self._buses:
                riders = sim.target_riders(datetime.now())
                sim.riders = riders

                # One ping per simulated rider: the crowd aggregation
                # counts *distinct user ids* seen recently, so this is
                # what actually produces a fullness percentage.
                for seat in range(riders):
                    db.add(
                        UserPing(
                            user_id=DEMO_USER_ID_BASE
                            + sim.bus_id * 1000
                            + seat,
                            latitude=sim.latitude
                            + random.uniform(-0.00012, 0.00012),
                            longitude=sim.longitude
                            + random.uniform(-0.00012, 0.00012),
                            speed=SPEED_KMH
                            + random.uniform(-3.0, 3.0),
                            bus_id=sim.bus_id,
                            timestamp=now,
                        )
                    )

                if self.ticks % REPORT_EVERY_N_TICKS == 0:
                    # Pick the 1-5 level whose meaning in
                    # CROWD_LEVEL_TO_PERCENTAGE is closest to the load
                    # we're actually simulating, so the report agrees
                    # with the rider count instead of fighting it in
                    # the aggregation average.
                    percent = 100.0 * riders / max(1, sim.capacity)
                    level = min(
                        CROWD_LEVEL_TO_PERCENTAGE,
                        key=lambda lvl: abs(
                            CROWD_LEVEL_TO_PERCENTAGE[lvl] - percent
                        ),
                    )

                    db.add(
                        CrowdReport(
                            user_id=DEMO_USER_ID_BASE + sim.bus_id,
                            bus_id=sim.bus_id,
                            crowd_level=level,
                            timestamp=now,
                        )
                    )

            # Prune as we go so a long demo doesn't grow bus.db without
            # bound. Only ever touches demo rows.
            cutoff = now - timedelta(minutes=PING_RETENTION_MINUTES)

            db.query(UserPing).filter(
                UserPing.user_id >= DEMO_USER_ID_BASE,
                UserPing.timestamp < cutoff,
            ).delete(synchronize_session=False)

            db.query(CrowdReport).filter(
                CrowdReport.user_id >= DEMO_USER_ID_BASE,
                CrowdReport.timestamp < cutoff,
            ).delete(synchronize_session=False)

            db.commit()

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # -----------------------------------------------------
    # Status
    # -----------------------------------------------------

    def snapshot(self) -> list[dict]:
        return [
            {
                "bus_id": sim.bus_id,
                "bus_number": sim.bus_number,
                "latitude": round(sim.latitude, 6),
                "longitude": round(sim.longitude, 6),
                "speed_kmh": SPEED_KMH,
                "simulated_riders": sim.riders,
                "capacity": sim.capacity,
            }
            for sim in self._buses
        ]


# ---------------------------------------------------------
# Purging
# ---------------------------------------------------------

def purge_demo_data() -> dict[str, int]:
    """
    Remove every row this simulator has ever written.

    Real rider data is untouched: the filter is the reserved demo
    user_id range and nothing else.
    """

    with _db_lock:
        return _purge_demo_data_locked()


def _purge_demo_data_locked() -> dict[str, int]:
    db: Session = SessionLocal()

    try:
        pings = (
            db.query(UserPing)
            .filter(UserPing.user_id >= DEMO_USER_ID_BASE)
            .delete(synchronize_session=False)
        )

        checkins = (
            db.query(CheckIn)
            .filter(CheckIn.user_id >= DEMO_USER_ID_BASE)
            .delete(synchronize_session=False)
        )

        reports = (
            db.query(CrowdReport)
            .filter(CrowdReport.user_id >= DEMO_USER_ID_BASE)
            .delete(synchronize_session=False)
        )

        # Observations recorded during the demo go too. The banner
        # promises nothing generated survives the demo, and that has to
        # cover the training set, not just what's on screen - a model
        # quietly fitted to simulated riders would be the one piece of
        # fake data nobody could see.
        db.query(CrowdObservation).filter(
            CrowdObservation.is_simulated == 1
        ).delete(synchronize_session=False)

        db.commit()

        return {
            "pings": pings or 0,
            "checkins": checkins or 0,
            "reports": reports or 0,
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Single process-wide instance.
simulator = DemoSimulator()