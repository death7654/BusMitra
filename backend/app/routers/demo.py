import asyncio

from fastapi import APIRouter, HTTPException, Query, status

from ..schemas import (
    DemoBusState,
    DemoResetResponse,
    DemoStatusResponse,
)
from ..services import demo as demo_service


router = APIRouter(prefix="/api/demo", tags=["Demo mode"])


def _status(message: str) -> DemoStatusResponse:
    sim = demo_service.simulator

    return DemoStatusResponse(
        available=demo_service.ENABLED,
        running=sim.running,
        started_at=sim.started_at if sim.running else None,
        ticks=sim.ticks,
        tick_seconds=demo_service.TICK_SECONDS,
        simulated_buses=[
            DemoBusState(**bus) for bus in sim.snapshot()
        ],
        message=message,
    )


def _require_available() -> None:
    if not demo_service.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Demo mode is disabled on this server "
                "(BUSMITRA_DEMO_ENABLED=0)."
            ),
        )


@router.get("/status", response_model=DemoStatusResponse)
def demo_status():
    """
    Whether the fleet simulation is running, and where it has put
    each bus. Safe to poll.
    """

    sim = demo_service.simulator

    if not demo_service.ENABLED:
        return _status("Demo mode is disabled on this server.")

    if sim.running:
        return _status(
            f"Demo mode is running - {len(sim.snapshot())} simulated "
            "buses. All crowd numbers you see are generated."
        )

    return _status("Demo mode is off. Live data only.")


@router.post("/start", response_model=DemoStatusResponse)
async def start_demo():
    """
    Start the fleet simulation.

    Simulated buses drive their real routes and write ordinary pings
    and crowd reports, so every other endpoint shows live-looking data
    without any special handling.
    """

    _require_available()

    try:
        await demo_service.simulator.start()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return _status(
        "Demo mode started. Every crowd number from here on is "
        "simulated, not real."
    )


@router.post("/stop", response_model=DemoStatusResponse)
async def stop_demo(
    purge: bool = Query(
        default=True,
        description=(
            "Also delete the simulated pings and reports. Leave this "
            "on unless you want the generated history to stick around."
        ),
    ),
):
    """
    Stop the simulation and, by default, remove the data it produced.
    """

    removed = await demo_service.simulator.stop(purge=purge)

    if purge:
        return _status(
            f"Demo mode stopped and {removed} simulated record"
            f"{'s' if removed != 1 else ''} removed."
        )

    return _status(
        "Demo mode stopped. Simulated records were left in place."
    )


@router.post("/reset", response_model=DemoResetResponse)
async def reset_demo():
    """
    Delete all simulated data without touching real rider data.

    Useful after a demo, or when a previous run was interrupted and
    left generated rows behind.
    """

    await demo_service.simulator.stop(purge=False)

    # Off the event loop: this is a synchronous SQLAlchemy delete that
    # may also block on _db_lock waiting for an in-flight tick, and
    # holding up every other request while it does would make the whole
    # API stall for the length of the purge.
    counts = await asyncio.to_thread(demo_service.purge_demo_data)
    total = sum(counts.values())

    return DemoResetResponse(
        success=True,
        deleted_pings=counts["pings"],
        deleted_checkins=counts["checkins"],
        deleted_reports=counts["reports"],
        message=(
            f"Removed {total} simulated record"
            f"{'s' if total != 1 else ''}. Real rider data was "
            "not touched."
        ),
    )