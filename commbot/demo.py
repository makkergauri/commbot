"""
Public demo mode, for the hosted copy anyone can open.

The hosted server has no gateway phone and a disk that is wiped whenever the
host puts it to sleep. So the demo keeps the one thing that is genuinely live,
the government alert feed, and fills in the rest honestly:

  - a handful of obviously fake subscribers, so Coverage isn't empty
  - messages are rendered but never actually sent
  - the approve/reject buttons are switched off for visitors

Everything a visitor sees about alerts is real and current. Everything about
people is labelled as demo data.
"""
from __future__ import annotations

import logging
import threading

from .models import Subscriber

log = logging.getLogger(__name__)

# 90000 000xx is a reserved-looking range nobody will mistake for a real person.
DEMO_SUBSCRIBERS = [
    ("+919000000001", "Idukki", "hi"),
    ("+919000000002", "Kottayam", "en"),
    ("+919000000003", "Ranchi", "hi"),
    ("+919000000004", "Jhargram", "hi"),
    ("+919000000005", "Muzaffarpur", "hi"),
    ("+919000000006", "Dibrugarh", "en"),
    ("+919000000007", "Bahraich", "hi"),
    ("+919000000008", "Chennai", "en"),
]


def seed_subscribers(store) -> None:
    for phone, district, lang in DEMO_SUBSCRIBERS:
        store.upsert_subscriber(Subscriber(phone=phone, district=district, lang=lang))
    log.info("Demo mode: seeded %d fake subscribers", len(DEMO_SUBSCRIBERS))


def start_background_poller(settings, store, sender) -> threading.Thread:
    """
    Run the fetch loop inside the web process.

    On a free host there's only one process, and it only exists while someone
    is looking at the page. Starting the loop here means the very first visit
    after a cold start kicks off a fresh fetch from SACHET.
    """
    from .llm import get_llm
    from .pipeline import run_forever

    thread = threading.Thread(target=run_forever, args=(settings, store, sender, get_llm(settings)),
                              name="commbot-poller", daemon=True)
    thread.start()
    log.info("Background poller started (every %ds)", settings.poll_interval_sec)
    return thread