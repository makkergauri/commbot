"""
SMS senders. Pick one with SMS_PROVIDER in your .env.

  console       prints messages to the terminal. Use this while developing
                so you don't text real people by accident.
  android       an Android phone on the same Wi-Fi running the open-source
                "SMS Gateway for Android" app, sending through its own SIM.
                This is the offline fallback: no internet needed, only cell
                signal, and no DLT registration because it's a normal phone
                sending a normal SMS.
  http_gateway  any other HTTP-to-SMS gateway; adjust payload() to match.

A note on India: commercial bulk/A2P SMS must go through TRAI's DLT system
(registered sender ID + pre-approved message templates). Sort this out BEFORE
a disaster, it takes time. The fixed templates in localize.py help here,
because DLT wants templates anyway.
"""
from __future__ import annotations

import itertools
import logging
import time

import requests

log = logging.getLogger(__name__)


class SMSSender:
    name = "base"

    def send(self, to: str, body: str) -> tuple[bool, str]:
        raise NotImplementedError

    def send_with_retry(self, to: str, body: str, attempts: int = 3) -> tuple[bool, str]:
        # Networks are flaky during disasters. Retry a couple of times with
        # backoff before giving up and logging the failure.
        delay, ref = 1.0, ""
        for attempt in range(attempts):
            ok, ref = self.send(to, body)
            if ok:
                return True, ref
            if attempt < attempts - 1:
                time.sleep(delay)
                delay *= 2
        log.error("SMS to %s failed after %d attempts: %s", to, attempts, ref)
        return False, ref


class ConsoleSender(SMSSender):
    name = "console"
    _counter = itertools.count(1)

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.outbox: list[tuple[str, str]] = []  # handy for tests

    def send(self, to: str, body: str) -> tuple[bool, str]:
        from ..localize import sms_segments

        self.outbox.append((to, body))
        if not self.quiet:
            print(f"\n--- SMS to {to} ({len(body)} chars, {sms_segments(body)} segment(s)) ---")
            print(body)
        return True, f"console-{next(self._counter)}"


class AndroidGatewaySender(SMSSender):
    """
    Talks to the local server of the "SMS Gateway for Android" app.

    The app shows its IP address and basic-auth credentials on its Local
    Server screen. Messages go out through the phone's own SIM, which means
    real delivery to real numbers with no provider account at all. It's slow
    (a couple of messages a second at best) and the phone has to be awake and
    on the same network, so treat it as the fallback path, not the main one.
    """

    name = "android"

    def __init__(self, url: str, user: str, password: str):
        if not url:
            raise ValueError("android gateway needs SMS_GATEWAY_URL, e.g. http://192.168.1.5:8080")
        base = url.rstrip("/")
        self.url = base if base.endswith("/message") else base + "/message"
        self.auth = (user, password) if user else None

    def send(self, to: str, body: str) -> tuple[bool, str]:
        payload = {"textMessage": {"text": body}, "phoneNumbers": [to]}
        try:
            resp = requests.post(self.url, json=payload, auth=self.auth, timeout=20)
        except requests.RequestException as exc:
            # Phone asleep, off the network, or a wrong IP: all look like this.
            return False, f"network: {exc}"
        if not resp.ok:
            return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
        try:
            # The app queues the message and returns an id we can log.
            return True, str(resp.json().get("id", ""))
        except ValueError:
            return True, ""


class HTTPGatewaySender(SMSSender):
    """
    Generic JSON POST, for any other gateway. Check your app's docs and
    tweak payload() to match what it expects.
    """

    name = "http_gateway"

    def __init__(self, url: str, token: str = ""):
        if not url:
            raise ValueError("http_gateway needs SMS_GATEWAY_URL")
        self.url = url
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def payload(self, to: str, body: str) -> dict:
        return {"to": to, "message": body}

    def send(self, to: str, body: str) -> tuple[bool, str]:
        try:
            resp = requests.post(self.url, json=self.payload(to, body),
                                 headers=self.headers, timeout=10)
            if resp.ok:
                return True, resp.text[:100]
            return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
        except requests.RequestException as exc:
            return False, f"network: {exc}"


def get_sender(settings) -> SMSSender:
    provider = settings.sms_provider.lower()
    if provider in ("android", "android_gateway"):
        return AndroidGatewaySender(settings.gateway_url, settings.gateway_user, settings.gateway_pass)
    if provider == "http_gateway":
        return HTTPGatewaySender(settings.gateway_url, settings.gateway_token)
    return ConsoleSender()