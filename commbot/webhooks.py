"""
The web side of CommBot: the control room dashboard and the inbound SMS hook.

People text commands to the SIM in the gateway phone (JOIN, STATUS, SHELTER,
HELPLINE, STOP). The SMS Gateway app forwards each received message here as
a webhook, we work out the reply, and we send it back out through the same
SIM. So the whole two-way loop runs on one phone and one laptop, with no
messaging provider in between.

Set the webhook up in the app (Local Server -> webhooks), pointing at:
    POST https://<your-public-address>/sms?token=<WEBHOOK_TOKEN>
"""
from __future__ import annotations

import logging
import re

from flask import Flask, abort, redirect, request

from .channels import get_sender
from .commands import handle_sms_command
from .dashboard import create_blueprint

log = logging.getLogger(__name__)

# The gateway app and a plain form post name these fields differently, so
# accept whichever turns up rather than tying ourselves to one sender.
PHONE_FIELDS = ("phoneNumber", "phone", "from", "From", "sender")
TEXT_FIELDS = ("message", "text", "body", "Body")


def is_person(phone: str) -> bool:
    """
    Only real mobile numbers get a reply. The gateway forwards EVERY SMS the
    SIM receives, so bank OTPs and shortcodes ("VM-HDFCBK", "57575") arrive
    here too. Those must never be logged or answered.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return len(digits) == 10 and digits[0] in "6789"


def _first(data: dict, names) -> str:
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def parse_incoming(payload: dict, form: dict) -> tuple[str, str]:
    """Pull (phone, text) out of whatever shape the gateway sent."""
    # The app wraps the real message in {"event": ..., "payload": {...}}.
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    phone = _first(inner, PHONE_FIELDS) or _first(form, PHONE_FIELDS)
    text = _first(inner, TEXT_FIELDS) or _first(form, TEXT_FIELDS)
    return phone, text


def create_app(settings, store, sender=None) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(settings, store))
    # Replies go out the same way alerts do.
    sender = sender or get_sender(settings)

    @app.get("/")
    def home():
        # Nothing useful lives at the root, and a bare 404 here is baffling
        # when you're just checking the server is up.
        return redirect("/dashboard")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/sms")
    def sms_inbound():
        if settings.webhook_token and request.args.get("token") != settings.webhook_token:
            abort(403)

        payload = request.get_json(silent=True) or {}
        phone, text = parse_incoming(payload, request.form.to_dict())
        if not phone:
            return {"ok": False, "error": "no phone number in request"}, 400
        if not is_person(phone):
            # Not a person: an OTP, a bank alert, a promo. Drop it without
            # logging the text, and say 200 so the gateway doesn't retry.
            return {"ok": True, "ignored": True}

        reply = handle_sms_command(store, phone, text, settings.default_lang)
        ok, ref = sender.send_with_retry(phone, reply)
        # Log the command word only, never the full text of someone's message.
        command = (text.split() or ["(empty)"])[0].upper()[:12]
        log.info("Command %s from %s -> replied (%s)", command, phone, "sent" if ok else ref)
        return {"ok": ok, "reply": reply}

    return app