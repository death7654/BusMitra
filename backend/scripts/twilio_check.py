"""Send one trial SMS exactly like Twilio's Console "Try out SMS" snippet.

Run from the backend folder, with the same env vars the server uses:

    python scripts/twilio_check.py +918618435857

If this succeeds (prints HTTP 201 and status 'queued') but the API still
fails with 572006, the server is running old code or different env vars.
Uses httpx, which is already in requirements.txt.
"""
import os
import sys

import httpx

sid = os.environ["TWILIO_ACCOUNT_SID"].strip()
token = os.environ["TWILIO_AUTH_TOKEN"].strip()
sender = os.environ.get("TWILIO_FROM_NUMBER", "+17372508034").strip()
to = sys.argv[1] if len(sys.argv) > 1 else "+918618435857"
template = os.environ.get("TWILIO_TRIAL_TEMPLATE", "sms_account_alerts")

res = httpx.post(
    f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
    auth=(sid, token),
    data={"To": to, "From": sender, "Body": template},
    timeout=15.0,
)
print("HTTP", res.status_code)
body = res.json()
print({k: body.get(k) for k in ("sid", "status", "error_code", "error_message", "code", "message")})
print("Env seen by this process: TWILIO_TRIAL_MODE=%r TWILIO_EXTRA_PARAMS=%r" % (
    os.environ.get("TWILIO_TRIAL_MODE"), os.environ.get("TWILIO_EXTRA_PARAMS")))
