from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, CrowdReport
from ..schemas import CrowdReportRequest, CrowdReportResponse
from ..services import events
from ..services.crowd_aggregation import (
    MIN_REPORT_INTERVAL_SECONDS,
    aggregate_bus_crowd,
    get_last_report,
    get_report_window_cutoff,
)


router = APIRouter(
    prefix="/api",
    tags=["Crowd"],
)


@router.post("/report", response_model=CrowdReportResponse)
def create_crowd_report(
    report: CrowdReportRequest,
    db: Session = Depends(get_db),
):
    """
    Record one rider's judgement of how full a bus is.

    Two things this endpoint used to get wrong:

      * It accepted unlimited reports from the same device. Since the
        aggregate was a flat mean over rows, tapping "packed" five
        times moved the number five times as far as tapping it once.
        Now a device may refresh its own report once a minute, and the
        aggregation counts only each device's latest one regardless.
      * It returned a fixed acknowledgement string, so reporting felt
        like it did nothing - the figure on screen was unchanged until
        the next poll, and often looked unchanged even then. It now
        returns the recomputed estimate, so the reporter can see their
        contribution land.

    Older rows are kept rather than overwritten: they don't get to vote
    twice, but they are real observations of a real bus and belong in
    the training set.
    """

    bus = (
        db.query(Bus)
        .filter(Bus.id == report.bus_id)
        .first()
    )

    if bus is None:
        raise HTTPException(
            status_code=404,
            detail="Bus not found.",
        )

    # ---------------------------------------------------------
    # One vote per device per cooldown
    # ---------------------------------------------------------

    previous = get_last_report(
        db=db,
        user_id=report.user_id,
        bus_id=report.bus_id,
    )

    now = datetime.utcnow()

    if previous is not None:
        elapsed = (now - previous.timestamp).total_seconds()

        if elapsed < MIN_REPORT_INTERVAL_SECONDS:
            wait = int(MIN_REPORT_INTERVAL_SECONDS - elapsed) + 1

            # 429 rather than a silent no-op: the client shows the
            # remaining wait on the button instead of pretending the
            # tap was accepted. Retry-After is the standard way to say
            # how long, so a generic HTTP client handles it too.
            raise HTTPException(
                status_code=429,
                detail=(
                    f"You can update your report in {wait}s."
                ),
                headers={"Retry-After": str(wait)},
            )

    # Whether this supersedes a report of theirs that was still
    # counting, as opposed to being their first in this window.
    replaced_previous = (
        previous is not None
        and previous.timestamp >= get_report_window_cutoff()
    )

    new_report = CrowdReport(
        user_id=report.user_id,
        bus_id=report.bus_id,
        crowd_level=report.crowd_level,
        timestamp=now,
    )

    db.add(new_report)
    db.commit()

    # ---------------------------------------------------------
    # Show the reporter what they just changed
    # ---------------------------------------------------------

    crowd = aggregate_bus_crowd(db=db, bus_id=report.bus_id)

    # A report is exactly the kind of change other riders want
    # immediately rather than on their next poll: someone standing at
    # the stop has just told us this bus is packed. Push it.
    if crowd:
        events.bus.publish(
            events.BUS_STATUS,
            {
                "bus_id": bus.id,
                "bus_number": bus.bus_number,
                "overall_fullness": crowd["overall_fullness"],
                "crowd_source": crowd["crowd_source"],
                "trend": crowd["trend"],
                "active_passengers": crowd["active_passengers"],
                "reporter_count": crowd["reporter_count"],
                "reason": "report",
            },
        )

    reporter_count = crowd["reporter_count"] if crowd else 1
    overall = crowd["overall_fullness"] if crowd else None

    if overall is None:
        message = "Report submitted."
    elif reporter_count > 1:
        message = (
            f"Thanks - {bus.bus_number} now reads {round(overall)}% full "
            f"from {reporter_count} riders."
        )
    else:
        message = (
            f"Thanks - {bus.bus_number} now reads {round(overall)}% full. "
            "You're the only rider reporting right now."
        )

    return CrowdReportResponse(
        success=True,
        user_id=report.user_id,
        bus_id=report.bus_id,
        crowd_level=report.crowd_level,
        message=message,
        overall_fullness=overall,
        reporter_count=reporter_count,
        replaced_previous=replaced_previous,
        next_report_in_seconds=MIN_REPORT_INTERVAL_SECONDS,
    )