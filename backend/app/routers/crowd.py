from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, CrowdReport
from ..schemas import CrowdReportRequest, CrowdReportResponse


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
    Store a manual crowd report for a bus.
    """

    # ---------------------------------------------------------
    # Verify that the bus exists
    # ---------------------------------------------------------

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
    # Create crowd report
    # ---------------------------------------------------------

    new_report = CrowdReport(
        user_id=report.user_id,
        bus_id=report.bus_id,
        crowd_level=report.crowd_level,
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    # ---------------------------------------------------------
    # Return response
    # ---------------------------------------------------------

    return CrowdReportResponse(
        success=True,
        user_id=report.user_id,
        bus_id=report.bus_id,
        crowd_level=report.crowd_level,
        message="Crowd report submitted successfully.",
    )