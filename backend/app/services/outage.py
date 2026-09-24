"""
Bus outage reporting.

Riders can report that a bus everyone is waiting for isn't showing up
- broken down, cancelled, or just never arrived. This is a different
signal from a crowd report: a crowd report says a bus is busy, an
outage report says it might not be coming at all, and the two must
never be blended into one number.

An outage report is a claim, not a fact, so it is never taken alone:

  * It only becomes visible to other riders once at least
    OUTAGE_MIN_REPORTS different people have reported it within
    OUTAGE_WINDOW_MINUTES - one rider annoyed at a bus running two
    minutes late shouldn't be able to paint it "out of service" for
    everyone else.
  * It clears itself the moment better evidence turns up. A GPS ping
    or an open check-in newer than the reports means someone with the
    app is physically on that bus right now, which outranks any number
    of reports saying it doesn't exist.
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import CheckIn, OutageReport, UserPing

OUTAGE_WINDOW_MINUTES = 30
OUTAGE_MIN_REPORTS = 2

REASON_LABELS = {
    "not_running": "not running",
    "breakdown": "broken down",
    "never_arrived": "never arrived",
    "accident": "in an accident",
    "other": "having some other issue",
}


def _window_cutoff() -> datetime:
    return datetime.utcnow() - timedelta(minutes=OUTAGE_WINDOW_MINUTES)


def _latest_positive_evidence_at(db: Session, bus_id: int) -> datetime | None:
    """
    The most recent moment something showed this bus actually running:
    a GPS ping from a phone aboard it, or a check-in nobody has left.
    """

    latest_ping = (
        db.query(UserPing.timestamp)
        .filter(UserPing.bus_id == bus_id)
        .order_by(UserPing.timestamp.desc())
        .first()
    )

    latest_checkin = (
        db.query(CheckIn.timestamp)
        .filter(CheckIn.bus_id == bus_id, CheckIn.checked_out_at.is_(None))
        .order_by(CheckIn.timestamp.desc())
        .first()
    )

    candidates = [row[0] for row in (latest_ping, latest_checkin) if row is not None]

    return max(candidates) if candidates else None


def get_outage_status(db: Session, bus_id: int) -> dict:
    """
    Current outage status for one bus, as a plain dict matching the
    OutageStatus schema's fields.
    """

    reports = (
        db.query(OutageReport)
        .filter(
            OutageReport.bus_id == bus_id,
            OutageReport.timestamp >= _window_cutoff(),
        )
        .order_by(OutageReport.timestamp.desc())
        .all()
    )

    if not reports:
        return {
            "reported_out_of_service": False,
            "outage_report_count": 0,
            "outage_reasons": [],
            "last_outage_report_at": None,
        }

    distinct_reporters = {report.user_id for report in reports}
    newest_report_at = reports[0].timestamp

    evidence_at = _latest_positive_evidence_at(db, bus_id)
    superseded = evidence_at is not None and evidence_at > newest_report_at

    # Most recent reason first, de-duplicated, without losing order.
    reasons = list(dict.fromkeys(report.reason for report in reports))

    return {
        "reported_out_of_service": (
            not superseded and len(distinct_reporters) >= OUTAGE_MIN_REPORTS
        ),
        "outage_report_count": len(distinct_reporters),
        "outage_reasons": reasons,
        "last_outage_report_at": newest_report_at,
    }
