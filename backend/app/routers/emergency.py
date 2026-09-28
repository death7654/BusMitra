import base64
import binascii
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import DATA_DIR, get_db
from ..models import BusIssueReport, Bus, EmergencyReport
from ..routers.admin import require_admin_strict
from ..schemas import (
    BusIssueRequest,
    EmergencyReportResponse,
    HealthAlertRequest,
    SosReportRequest,
)


router = APIRouter(prefix="/api", tags=["Emergency"])

PHOTO_DIR = DATA_DIR / "sos_photos"
PHOTO_DIR.mkdir(exist_ok=True)

MAX_PHOTO_BYTES = 6 * 1024 * 1024
# Stops one device from filling the disk, while staying far above
# anything a genuine emergency would need.
MAX_REPORTS_PER_USER_PER_HOUR = 20


def _check_rate(db: Session, user_id: int) -> None:
    since = datetime.utcnow() - timedelta(hours=1)
    recent = (
        db.query(EmergencyReport)
        .filter(
            EmergencyReport.user_id == user_id,
            EmergencyReport.created_at >= since,
        )
        .count()
    )
    if recent >= MAX_REPORTS_PER_USER_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="Too many emergency reports from this device. Please call 112 directly.",
        )


def _decode_jpeg(data_url: str | None) -> bytes | None:
    """Return JPEG bytes from a data URL, or None if it isn't a usable photo."""
    if not data_url:
        return None
    try:
        b64 = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
        raw = base64.b64decode(b64, validate=True)
    except (IndexError, binascii.Error, ValueError):
        return None
    if len(raw) > MAX_PHOTO_BYTES or not raw.startswith(b"\xff\xd8\xff"):
        return None
    return raw


def _save_photo(report_id: int, which: str, data_url: str | None) -> str | None:
    raw = _decode_jpeg(data_url)
    if raw is None:
        return None
    name = f"{report_id}_{which}.jpg"
    (PHOTO_DIR / name).write_bytes(raw)
    return name


@router.post("/sos", response_model=EmergencyReportResponse)
def create_sos_report(
    report: SosReportRequest,
    db: Session = Depends(get_db),
):
    """
    Record an SOS. Never fails because of optional extras: a bad photo,
    an unknown bus or missing coordinates are dropped, not rejected.
    """
    _check_rate(db, report.user_id)

    bus_id = report.bus_id
    if bus_id is not None and db.query(Bus.id).filter(Bus.id == bus_id).first() is None:
        bus_id = None

    row = EmergencyReport(
        user_id=report.user_id,
        kind="sos",
        sos_type=report.sos_type or "trigger",
        details=(report.details or "").strip() or None,
        bus_id=bus_id,
        latitude=report.latitude,
        longitude=report.longitude,
        contact_name=report.contact_name,
        contact_phone=report.contact_phone,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    saved = 0
    for which, data in (("front", report.photo_front), ("back", report.photo_back)):
        name = _save_photo(row.id, which, data)
        if name:
            setattr(row, f"photo_{which}_path", name)
            saved += 1
    if saved:
        db.commit()

    print(
        f"[SOS] report #{row.id} type={row.sos_type} user={row.user_id} "
        f"bus={row.bus_id} at=({row.latitude}, {row.longitude}) photos={saved}"
    )

    message = "SOS received. Stay safe \u2014 your location has been shared."
    if (report.photo_front or report.photo_back) and saved == 0:
        message += " (Photos couldn't be attached.)"

    return EmergencyReportResponse(report_id=row.id, message=message)


@router.post("/health-alert", response_model=EmergencyReportResponse)
def create_health_alert(
    report: HealthAlertRequest,
    db: Session = Depends(get_db),
):
    _check_rate(db, report.user_id)

    bus_id = report.bus_id
    if bus_id is not None and db.query(Bus.id).filter(Bus.id == bus_id).first() is None:
        bus_id = None

    row = EmergencyReport(
        user_id=report.user_id,
        kind="health",
        bus_id=bus_id,
        latitude=report.latitude,
        longitude=report.longitude,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    print(f"[HEALTH] alert #{row.id} user={row.user_id} bus={row.bus_id}")

    return EmergencyReportResponse(
        report_id=row.id,
        message="Driver alerted and your location shared. Call 108 if it's serious.",
    )


@router.post("/bus-issue", response_model=EmergencyReportResponse)
def create_bus_issue(
    report: BusIssueRequest,
    db: Session = Depends(get_db),
):
    if db.query(Bus.id).filter(Bus.id == report.bus_id).first() is None:
        raise HTTPException(status_code=404, detail="Bus not found.")

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
        message="Thanks \u2014 this has been flagged.",
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
    rows = (
        db.query(EmergencyReport)
        .order_by(EmergencyReport.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "sos_type": r.sos_type,
            "details": r.details,
            "user_id": r.user_id,
            "bus_id": r.bus_id,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "contact_name": r.contact_name,
            "contact_phone": r.contact_phone,
            "has_front_photo": bool(r.photo_front_path),
            "has_back_photo": bool(r.photo_back_path),
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/emergency-reports/{report_id}/photo/{which}")
def get_emergency_photo(
    report_id: int,
    which: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_strict),
):
    if which not in ("front", "back"):
        raise HTTPException(status_code=404, detail="Photo not found.")
    row = db.query(EmergencyReport).filter(EmergencyReport.id == report_id).first()
    name = getattr(row, f"photo_{which}_path", None) if row else None
    if not name or not (PHOTO_DIR / name).is_file():
        raise HTTPException(status_code=404, detail="Photo not found.")
    return FileResponse(PHOTO_DIR / name, media_type="image/jpeg")
