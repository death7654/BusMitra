from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, OutageReport
from ..schemas import OutageReportRequest, OutageReportResponse, OutageStatus
from ..services import events
from ..services.outage import REASON_LABELS, get_outage_status


router = APIRouter(prefix="/api", tags=["Outage"])


@router.post("/outage-report", response_model=OutageReportResponse)
def create_outage_report(
    report: OutageReportRequest,
    db: Session = Depends(get_db),
):
    """
    Record one rider's claim that a bus isn't running.

    Unlike a crowd report this is never rate-limited to one per
    cooldown - if the same bus never shows up twice in a row, that's
    two genuine data points, not spam. What keeps a single report from
    being taken as fact is get_outage_status: it only reports the bus
    out of service once a second rider has said the same thing, and it
    stands down the moment live evidence (a GPS ping, an open
    check-in) shows the bus actually running.
    """

    bus = db.query(Bus).filter(Bus.id == report.bus_id).first()

    if bus is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

    db.add(
        OutageReport(
            user_id=report.user_id,
            bus_id=report.bus_id,
            reason=report.reason,
        )
    )
    db.commit()

    status = get_outage_status(db=db, bus_id=report.bus_id)

    if status["reported_out_of_service"]:
        # Worth pushing immediately: someone at the stop has just told
        # everyone else this bus may not be coming.
        events.bus.publish(
            events.OUTAGE_REPORTED,
            {
                "bus_id": bus.id,
                "bus_number": bus.bus_number,
                "outage_report_count": status["outage_report_count"],
                "outage_reasons": status["outage_reasons"],
            },
        )

        message = (
            f"Thanks \u2014 {status['outage_report_count']} riders have now "
            f"reported {bus.bus_number} as "
            f"{REASON_LABELS.get(report.reason, report.reason)}."
        )
    else:
        message = (
            "Thanks, noted. It'll show as reported to other riders once "
            "someone else confirms it too."
        )

    return OutageReportResponse(
        success=True,
        user_id=report.user_id,
        bus_id=report.bus_id,
        reason=report.reason,
        message=message,
        status=OutageStatus(**status),
    )


@router.get("/bus/{bus_id}/outage", response_model=OutageStatus)
def get_bus_outage(bus_id: int, db: Session = Depends(get_db)):
    bus = db.query(Bus).filter(Bus.id == bus_id).first()

    if bus is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

    return OutageStatus(**get_outage_status(db=db, bus_id=bus_id))
