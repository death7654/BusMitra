import base64
import random
import re

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import app
from app.services import sos as sos_service

client = TestClient(app)

# Captured at import, before the autouse fixture swaps send_sms for a stub.
REAL_SEND_SMS = sos_service.send_sms

# Fresh number per run: the tests share the real SQLite file, and the
# per-number rate limit would otherwise trip on leftovers from earlier runs.
UID = random.randint(10_000_000, 90_000_000)
PHONE = str(random.randint(6_000_000_000, 9_999_999_999))

JPEG = b"\xff\xd8\xff\xe0" + b"fakejpegbody" * 10
DATA_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSMITRA_SOS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("BUSMITRA_SOS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BUSMITRA_PUBLIC_URL", "https://example.test")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550001111")
    sent = []
    monkeypatch.setattr(
        sos_service, "send_sms", lambda to, body: sent.append((to, body)) or True
    )
    return sent


def _post(uid, phone=PHONE, **extra):
    payload = {
        "user_id": uid,
        "sos_type": "trigger",
        "details": "help <b>me</b>",
        "latitude": 12.0,
        "longitude": 75.0,
        "contact_phone": phone,
        "photo_front": DATA_URL,
        "photo_back": DATA_URL,
    }
    payload.update(extra)
    return client.post("/api/sos", json=payload)


def test_sms_sent_and_link_shows_decrypted_photos(env):
    r = _post(UID + 1)
    assert r.status_code == 200
    body = r.json()
    assert body["sms_status"] == "sent" and body["photos_saved"] == 2
    to, text = env[0]
    assert to == "+91" + PHONE
    assert "maps.google.com/?q=12.00000,75.00000" in text
    url = re.search(r"https://example.test(\S+)", text).group(1)
    page = client.get(url)
    assert page.status_code == 200
    assert base64.b64encode(JPEG).decode() in page.text
    assert "<b>me</b>" not in page.text and "&lt;b&gt;me" in page.text
    assert page.headers["cache-control"] == "no-store"


def test_photos_encrypted_at_rest(tmp_path):
    _post(UID + 2, phone=None)
    files = list(tmp_path.glob("*.enc"))
    assert files and all(JPEG not in f.read_bytes() for f in files)


def test_wrong_token_and_bad_id_are_identical_404(env):
    _post(UID + 3)
    url = re.search(r"https://example.test(\S+)", env[0][1]).group(1)
    bad = client.get(re.sub(r"t=.*", "t=" + "x" * 30, url))
    missing = client.get("/api/sos/99999999/view?t=" + "x" * 30)
    assert bad.status_code == missing.status_code == 404
    assert bad.json() == missing.json()


def test_no_key_drops_photos_never_plaintext(monkeypatch, tmp_path, env):
    monkeypatch.delenv("BUSMITRA_SOS_KEY")
    r = _post(UID + 4)
    assert r.json()["photos_saved"] == 0
    assert not list(tmp_path.glob("*"))
    assert "could not be stored securely" in r.json()["message"]


def test_not_configured_is_honest(monkeypatch, env):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN")
    r = _post(UID + 5)
    assert r.json()["sms_status"] == "not_configured"
    assert not env and "has been texted" not in r.json()["message"]


def test_invalid_number_and_no_contact(env):
    assert _post(UID + 6, phone="abc").json()["sms_status"] == "invalid_number"
    assert _post(UID + 7, phone=None).json()["sms_status"] == "not_requested"
    assert not env


def test_rate_limit_per_number(env):
    # Fresh number each run: the tests share the real SQLite file.
    phone = "+1415" + str(random.randint(5000000, 5999999))
    base = random.randint(1_000_000, 9_000_000)
    statuses = [_post(base + i, phone=phone).json()["sms_status"] for i in range(5)]
    assert statuses[:3] == ["sent"] * 3
    assert statuses[3:] == ["rate_limited"] * 2
    assert len(env) == 3


def test_bad_photo_rejected_but_alert_accepted(env):
    r = _post(UID + 8, photo_front="data:image/jpeg;base64,AAAA", photo_back=None,
              contact_phone="+14155550123")
    assert r.status_code == 200 and r.json()["photos_saved"] == 0


def test_out_of_range_location_does_not_422(env):
    assert _post(UID + 9, latitude=999, contact_phone="+14155550199").status_code == 200


# ---------------------------------------------------------------------
# Twilio behaviour (real send_sms, HTTP mocked)
# ---------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload


# Shape of the response Twilio returned for the trial "Try out SMS" call.
QUEUED = {
    "sid": "SMb7d984d0e915edec2175ea7cbf2e3ab5",
    "status": "queued",
    "error_code": None,
    "error_message": None,
}


class _Real:
    send_sms = staticmethod(REAL_SEND_SMS)


def _real_send(monkeypatch, response, captured=None):
    """Use the genuine send_sms, faking only the HTTP call."""

    def fake_post(url, auth=None, data=None, timeout=None):
        if captured is not None:
            captured.update(url=url, data=data)
        return response

    monkeypatch.setattr(sos_service.httpx, "post", fake_post)
    return _Real


def test_send_sms_queued_counts_as_success(monkeypatch):
    real = _real_send(monkeypatch, _FakeResp(201, QUEUED))
    assert real.send_sms("+918618435857", "hi") is True


def test_send_sms_failed_status_in_2xx_is_failure(monkeypatch):
    bad = dict(QUEUED, status="failed", error_code=21608)
    real = _real_send(monkeypatch, _FakeResp(201, bad))
    assert real.send_sms("+918618435857", "hi") is False


def test_send_sms_http_error_is_failure(monkeypatch):
    real = _real_send(monkeypatch, _FakeResp(400, {"code": 21608, "message": "x"}))
    assert real.send_sms("+918618435857", "hi") is False


def test_trial_mode_sends_template_name_and_is_honest(monkeypatch, env):
    monkeypatch.setenv("TWILIO_TRIAL_MODE", "true")
    r = _post(UID + 20, phone="+1415" + str(random.randint(6000000, 6999999)))
    body = r.json()
    assert body["sms_status"] == "sent_trial"
    assert "does not include your location" in body["message"]
    _, text = env[0]
    # Twilio trial accounts reject anything but the template NAME (error 572006)
    assert text == "sms_account_alerts"


def test_trial_template_override_and_invalid_fallback(monkeypatch, env):
    monkeypatch.setenv("TWILIO_TRIAL_MODE", "1")
    monkeypatch.setenv("TWILIO_TRIAL_TEMPLATE", "sms_internal_alerts")
    _post(UID + 21, phone="+1415" + str(random.randint(7000000, 7999999)))
    assert env[0][1] == "sms_internal_alerts"
    monkeypatch.setenv("TWILIO_TRIAL_TEMPLATE", "Alert: custom text")
    _post(UID + 22, phone="+1415" + str(random.randint(8000000, 8999999)))
    assert env[1][1] == "sms_account_alerts"
