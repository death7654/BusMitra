"""
SOS support: encrypted evidence storage and the SMS to the trusted contact.

Configuration is all environment variables, so no secret lives in the
repo or the app binary:

  BUSMITRA_SOS_KEY          Fernet key. Without it, photos and free-text
                            details are DROPPED rather than stored in
                            plaintext. Generate one with:
                              python -c "from cryptography.fernet import
                              Fernet; print(Fernet.generate_key().decode())"
  TWILIO_ACCOUNT_SID        Twilio credentials. If any of the three is
  TWILIO_AUTH_TOKEN         missing, the alert is still stored and the
  TWILIO_FROM_NUMBER        response says honestly that no text was sent.
  BUSMITRA_PUBLIC_URL       Base URL used in the texted link. Falls back
                            to RENDER_EXTERNAL_URL, which Render sets.
  BUSMITRA_SOS_DATA_DIR     Where encrypted photos live. Point this at a
                            persistent disk on Render, or they are lost
                            on every deploy/restart.
  BUSMITRA_SOS_RETENTION_HOURS   Photos/details deleted after this long
                            (default 168 = 7 days).
  BUSMITRA_SOS_LINK_HOURS   How long the texted link works (default 24).
  BUSMITRA_DEFAULT_COUNTRY_CODE  Prefix for 10-digit numbers (default +91).
"""

import base64
import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..database import DATA_DIR
from ..models import SosReport

log = logging.getLogger("busmitra.sos")

MAX_PHOTO_BYTES = 3 * 1024 * 1024  # decoded JPEG size cap per photo
SMS_PER_NUMBER_PER_HOUR = 3
SMS_PER_USER_PER_HOUR = 5
SMS_MIN_GAP_SECONDS = 60  # same user, back to back


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def retention_hours() -> int:
    return _int_env("BUSMITRA_SOS_RETENTION_HOURS", 168)


def link_hours() -> int:
    return _int_env("BUSMITRA_SOS_LINK_HOURS", 24)


def photo_dir() -> Path:
    base = os.environ.get("BUSMITRA_SOS_DATA_DIR", "").strip()
    path = Path(base) if base else DATA_DIR / "sos_photos"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------

def _fernet() -> Fernet | None:
    key = os.environ.get("BUSMITRA_SOS_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        log.error("BUSMITRA_SOS_KEY is set but is not a valid Fernet key.")
        return None


def encryption_available() -> bool:
    return _fernet() is not None


def encrypt_text(text: str) -> str | None:
    f = _fernet()
    if f is None or not text:
        return None
    return f.encrypt(text.encode()).decode()


def decrypt_text(token: str | None) -> str:
    f = _fernet()
    if f is None or not token:
        return ""
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


# ---------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------

def _photo_path(report_id: int, which: str) -> Path:
    # which is only ever "front" or "back", never user input
    return photo_dir() / f"{report_id}_{which}.enc"


def decode_jpeg_data_url(data_url: str | None) -> bytes | None:
    """Return raw JPEG bytes, or None if this isn't a sane JPEG.

    Checks the data-URL prefix, the size cap and the JPEG magic bytes,
    so the server never stores or later serves arbitrary content.
    """
    if not data_url or not data_url.startswith("data:image/jpeg;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (ValueError, IndexError):
        return None
    if not raw or len(raw) > MAX_PHOTO_BYTES or raw[:3] != b"\xff\xd8\xff":
        return None
    return raw


def save_photo(report_id: int, which: str, jpeg: bytes) -> bool:
    f = _fernet()
    if f is None:
        return False
    _photo_path(report_id, which).write_bytes(f.encrypt(jpeg))
    return True


def load_photo(report_id: int, which: str) -> bytes | None:
    f = _fernet()
    path = _photo_path(report_id, which)
    if f is None or not path.exists():
        return None
    try:
        return f.decrypt(path.read_bytes())
    except InvalidToken:
        return None


def delete_photos(report_id: int) -> None:
    for which in ("front", "back"):
        try:
            _photo_path(report_id, which).unlink(missing_ok=True)
        except OSError:
            log.warning("Could not delete photo %s/%s", report_id, which)


def purge_expired(db: Session) -> int:
    """Delete photos and free-text details older than the retention window."""
    cutoff = datetime.utcnow() - timedelta(hours=retention_hours())
    old = (
        db.query(SosReport)
        .filter(SosReport.created_at < cutoff)
        .filter(
            (SosReport.has_photo_front.is_(True))
            | (SosReport.has_photo_back.is_(True))
            | (SosReport.details_enc.isnot(None))
        )
        .all()
    )
    for report in old:
        delete_photos(report.id)
        report.has_photo_front = False
        report.has_photo_back = False
        report.details_enc = None
    if old:
        db.commit()
    return len(old)


# ---------------------------------------------------------------------
# Link token
# ---------------------------------------------------------------------

def new_access_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    return token, hash_value(token)


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def token_matches(token: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_value(token or ""), stored_hash or "")


# ---------------------------------------------------------------------
# Phone numbers and SMS
# ---------------------------------------------------------------------

def normalise_phone(raw: str | None) -> str | None:
    """Best-effort E.164. Returns None if it doesn't look like a number."""
    if not raw:
        return None
    cleaned = re.sub(r"[^\d+]", "", raw)
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    else:
        default = os.environ.get("BUSMITRA_DEFAULT_COUNTRY_CODE", "+91").strip()
        default = default if default.startswith("+") else "+" + default
        local = cleaned.lstrip("0")
        digits = default[1:] + local if len(local) == 10 else cleaned
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        return None
    return "+" + digits


def sms_configured() -> bool:
    return all(
        os.environ.get(k, "").strip()
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")
    )


def sms_rate_limited(db: Session, user_id: int, phone_hash: str) -> bool:
    """Stops the endpoint being used to spam an arbitrary number.

    user_id is anonymous and client-generated, so the per-number limit
    is the one that actually protects a third party.
    """
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    sent = db.query(SosReport).filter(
        SosReport.sms_status == "sent", SosReport.sms_sent_at >= hour_ago
    )
    if sent.filter(SosReport.contact_phone_hash == phone_hash).count() >= (
        SMS_PER_NUMBER_PER_HOUR
    ):
        return True
    by_user = sent.filter(SosReport.user_id == user_id)
    if by_user.count() >= SMS_PER_USER_PER_HOUR:
        return True
    last = by_user.order_by(SosReport.sms_sent_at.desc()).first()
    return bool(
        last
        and last.sms_sent_at
        and (now - last.sms_sent_at).total_seconds() < SMS_MIN_GAP_SECONDS
    )


def public_base_url() -> str:
    url = (
        os.environ.get("BUSMITRA_PUBLIC_URL", "").strip()
        or os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    )
    return url.rstrip("/")


def send_sms(to_number: str, body: str) -> bool:
    """Send one text through Twilio's REST API. Never raises."""
    sid = os.environ["TWILIO_ACCOUNT_SID"].strip()
    token = os.environ["TWILIO_AUTH_TOKEN"].strip()
    sender = os.environ["TWILIO_FROM_NUMBER"].strip()
    try:
        res = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"To": to_number, "From": sender, "Body": body},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        log.error("Twilio request failed: %s", type(exc).__name__)
        return False
    if res.status_code >= 400:
        try:
            body = res.json()
        except ValueError:
            body = {}
        # Twilio's message can quote the destination number, so mask digits
        # before logging to keep the "never log the number" rule.
        reason = re.sub(r"\+?\d{6,}", "[number]", str(body.get("message", "")))
        log.error(
            "Twilio rejected SMS: HTTP %s code %s - %s (%s)",
            res.status_code, body.get("code"), reason, body.get("more_info"),
        )
        return False
    return True
