import base64
import html
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Bus, SosReport
from ..services import sos as sos_service


router = APIRouter(prefix="/api", tags=["SOS"])

MAX_DETAILS_CHARS = 1000


class SosRequest(BaseModel):
    """Field names match what the Tauri shell posts (see submit_sos_report).

    Everything except user_id is optional and is sanitised rather than
    rejected: an SOS should never bounce with a 422 because a latitude
    was slightly off or a photo was too big.
    """

    user_id: int = Field(..., gt=0)
    sos_type: str | None = None
    details: str | None = None
    bus_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_name: str | None = None  # accepted, deliberately not stored
    contact_phone: str | None = None
    photo_front: str | None = None
    photo_back: str | None = None

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v):
        return v if v is not None and -90 <= v <= 90 else None

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v):
        return v if v is not None and -180 <= v <= 180 else None


class SosResponse(BaseModel):
    success: bool
    message: str
    sms_status: str
    photos_saved: int = 0


def _clean_type(value: str | None) -> str:
    cleaned = "".join(c for c in (value or "trigger") if c.isalnum() or c in "_-")
    return cleaned[:32] or "trigger"


def _sms_body(
    bus_number: str | None,
    lat: float | None,
    lon: float | None,
    link: str | None,
) -> str:
    parts = [
        "BusMitra SOS: someone who listed you as their emergency contact "
        "has sent an alert"
        + (f" from bus {bus_number}." if bus_number else ".")
    ]
    if lat is not None and lon is not None:
        parts.append(f"Location: https://maps.google.com/?q={lat:.5f},{lon:.5f}")
    if link:
        parts.append(f"Photos and details (expires soon): {link}")
    parts.append("Please try calling them now.")
    return " ".join(parts)


@router.post("/sos", response_model=SosResponse)
def create_sos_report(
    req: SosRequest,
    db: Session = Depends(get_db),
):
    """
    Store an SOS alert and, if a contact number was given, text them.

    What actually happened is reported back truthfully in `message` and
    `sms_status`: the app shows that string to someone in an emergency,
    so it must never claim a text was sent when it wasn't.
    """

    sos_service.purge_expired(db)

    bus = db.query(Bus).filter(Bus.id == req.bus_id).first() if req.bus_id else None

    token, token_hash = sos_service.new_access_token()

    details = (req.details or "").strip()[:MAX_DETAILS_CHARS]
    phone = sos_service.normalise_phone(req.contact_phone)
    phone_hash = sos_service.hash_value(phone) if phone else None

    report = SosReport(
        user_id=req.user_id,
        bus_id=req.bus_id,
        sos_type=_clean_type(req.sos_type),
        details_enc=sos_service.encrypt_text(details),
        latitude=req.latitude,
        longitude=req.longitude,
        contact_phone_hash=phone_hash,
        access_token_hash=token_hash,
        sms_status="not_requested",
    )
    db.add(report)
    db.flush()  # need report.id for the photo filenames

    # -- photos: validated, then stored encrypted or not at all ---------
    photos_offered = 0
    photos_saved = 0
    for which, data_url in (("front", req.photo_front), ("back", req.photo_back)):
        if not data_url:
            continue
        photos_offered += 1
        jpeg = sos_service.decode_jpeg_data_url(data_url)
        if jpeg and sos_service.save_photo(report.id, which, jpeg):
            setattr(report, f"has_photo_{which}", True)
            photos_saved += 1

    # -- SMS -----------------------------------------------------------
    if req.contact_phone:
        if phone is None:
            report.sms_status = "invalid_number"
        elif not sos_service.sms_configured():
            report.sms_status = "not_configured"
        elif sos_service.sms_rate_limited(db, req.user_id, phone_hash):
            report.sms_status = "rate_limited"
        else:
            base = sos_service.public_base_url()
            link = (
                f"{base}/api/sos/{report.id}/view?t={token}"
                if base and (photos_saved or details)
                else None
            )
            body = _sms_body(
                bus.bus_number if bus else None,
                req.latitude,
                req.longitude,
                link,
            )
            if sos_service.send_sms(phone, body):
                report.sms_status = "sent"
                report.sms_sent_at = datetime.utcnow()
            else:
                report.sms_status = "failed"

    db.commit()

    return SosResponse(
        success=True,
        message=_message(report.sms_status, photos_offered, photos_saved),
        sms_status=report.sms_status,
        photos_saved=photos_saved,
    )


def _message(sms_status: str, offered: int, saved: int) -> str:
    saved_note = "Your alert was recorded."
    if offered and not saved:
        saved_note += " Your photos could not be stored securely."
    texts = {
        "sent": "Your alert was recorded and your contact has been texted.",
        "not_requested": saved_note + " No trusted contact is saved, so no text was sent.",
        "invalid_number": saved_note + " Your contact's number doesn't look valid, so no text was sent.",
        "not_configured": saved_note + " Texting isn't set up on the server, so please call your contact.",
        "rate_limited": saved_note + " A text to this contact was sent recently, so none was sent now.",
        "failed": saved_note + " The text to your contact could not be sent, so please call them.",
    }
    text = texts.get(sms_status, saved_note)
    if sms_status == "sent" and offered and not saved:
        text += " Your photos could not be stored securely."
    return text


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>BusMitra SOS</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;padding:16px;
background:#fff;color:#111;max-width:640px}}h1{{color:#b00020;font-size:1.3rem}}
img{{max-width:100%;border-radius:8px;margin:8px 0}}
a{{color:#0b57d0}}.m{{color:#555;font-size:.9rem}}</style></head><body>
<h1>SOS alert</h1>{body}</body></html>"""


@router.get("/sos/{report_id}/view", response_class=HTMLResponse)
def view_sos_report(
    report_id: int,
    t: str = Query(..., min_length=10, max_length=128),
    db: Session = Depends(get_db),
):
    """
    The page a contact reaches from the texted link.

    Wrong token, unknown id and expired link all return the same 404,
    so the endpoint can't be used to discover which alerts exist. The
    page is marked no-store/noindex and can't load anything remote.
    """

    report = db.query(SosReport).filter(SosReport.id == report_id).first()

    expired = report is not None and report.created_at < (
        datetime.utcnow() - timedelta(hours=sos_service.link_hours())
    )

    if (
        report is None
        or expired
        or not sos_service.token_matches(t, report.access_token_hash)
    ):
        raise HTTPException(status_code=404, detail="Not found.")

    bus = db.query(Bus).filter(Bus.id == report.bus_id).first() if report.bus_id else None

    rows = [
        f'<p class="m">Sent {html.escape(report.created_at.strftime("%d %b %Y %H:%M"))} UTC'
        + (f" &middot; bus {html.escape(bus.bus_number)}" if bus else "")
        + "</p>"
    ]
    if report.latitude is not None and report.longitude is not None:
        rows.append(
            '<p><a href="https://maps.google.com/?q='
            f'{report.latitude:.5f},{report.longitude:.5f}" rel="noreferrer">'
            "Open location in Maps</a></p>"
        )
    details = sos_service.decrypt_text(report.details_enc)
    if details:
        rows.append(f"<p>{html.escape(details)}</p>")
    for which, label in (("front", "Front camera"), ("back", "Back camera")):
        if getattr(report, f"has_photo_{which}"):
            jpeg = sos_service.load_photo(report.id, which)
            if jpeg:
                b64 = base64.b64encode(jpeg).decode()
                rows.append(
                    f'<p class="m">{label}</p>'
                    f'<img alt="{label}" src="data:image/jpeg;base64,{b64}">'
                )

    return HTMLResponse(
        _PAGE.format(body="".join(rows)),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": (
                "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
            ),
        },
    )
