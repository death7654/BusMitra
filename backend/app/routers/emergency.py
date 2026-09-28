from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, BusIssueReport, HealthAlert
from ..routers.admin import require_admin_strict
from ..schemas import (
    BusIssueRequest,
    EmergencyReportResponse,
    HealthAlertRequest,
)


# The SOS endpoint (photos, trusted contact, SMS) lives in routers/sos.py.
# This router holds the two lighter reports and their admin review.
router = APIRouter(prefix="/api", tags=["Emergency"])

# Stops one device from filling the table, while staying far above
# anything a genuine emergency would need.
MAX_REPORTS_PER_USER_PER_HOUR = 20


def _too_many(db: Session, model, user_id: int) -> bool:
    since = datetime.utcnow() - timedelta(hours=1)
    recent = (
        db.query(model)
        .filter(model.user_id == user_id, model.created_at >= since)
        .count()
    )
    return recent >= MAX_REPORTS_PER_USER_PER_HOUR


@router.post("/health-alert", response_model=EmergencyReportResponse)
def create_health_alert(
    report: HealthAlertRequest,
    db: Session = Depends(get_db),
):
    """
    Record a health alert with the rider's location.

    The message says exactly what happened: it was recorded. Nothing
    reaches the driver from here, and the rider is told to call 108.
    """

    if _too_many(db, HealthAlert, report.user_id):
        raise HTTPException(
            status_code=429,
            detail="Too many alerts from this device. Please call 108 directly.",
        )

    bus_id = report.bus_id

    if bus_id is not None and db.query(Bus.id).filter(Bus.id == bus_id).first() is None:
        bus_id = None

    row = HealthAlert(
        user_id=report.user_id,
        bus_id=bus_id,
        latitude=report.latitude,
        longitude=report.longitude,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return EmergencyReportResponse(
        report_id=row.id,
        message=(
            "Alert recorded with your location. This does not reach the "
            "driver directly: tell them or call 108 if it's serious."
        ),
    )


@router.post("/bus-issue", response_model=EmergencyReportResponse)
def create_bus_issue(
    report: BusIssueRequest,
    db: Session = Depends(get_db),
):
    if db.query(Bus.id).filter(Bus.id == report.bus_id).first() is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

    if _too_many(db, BusIssueReport, report.user_id):
        raise HTTPException(
            status_code=429,
            detail="Too many reports from this device. Please try again later.",
        )

    row = BusIssueReport(
        user_id=report.user_id,
        bus_id=report.bus_id,
        issue_type=report.issue_type,
        notes=(report.notes or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return EmergencyReportResponse(
        report_id=row.id,
        message="Thanks, this has been flagged.",
    )


# ---------------------------------------------------------
# Admin review (X-Admin-Token, same gate as fleet deletion)
# ---------------------------------------------------------

@router.get("/emergency-reports")
def list_emergency_reports(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_strict),
):
    alerts = (
        db.query(HealthAlert).order_by(HealthAlert.created_at.desc()).limit(limit).all()
    )
    issues = (
        db.query(BusIssueReport)
        .order_by(BusIssueReport.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "health_alerts": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "bus_id": r.bus_id,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "created_at": r.created_at.isoformat(),
            }
            for r in alerts
        ],
        "bus_issues": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "bus_id": r.bus_id,
                "issue_type": r.issue_type,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in issues
        ],
    }
