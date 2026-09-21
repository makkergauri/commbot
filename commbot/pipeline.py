"""
The main loop: collect -> extract -> score -> (review) -> dispatch.

Each step is its own function so you can run and test them separately,
and so one broken feed never stops the others.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from . import firebase_sync
from .extract import extract_facts
from .ingest import add_polygons, fetch_feed, fetch_rain_alerts
from .localize import render_sms
from .prioritize import score, should_send, subscriber_matches
from .utils import now_utc, parse_iso

log = logging.getLogger(__name__)


def source_name(feed: str) -> str:
    # Must be stable between runs, since it becomes part of the alert id.
    host = urlparse(feed).netloc
    return host or "local"


def collect_raw_alerts(settings, store=None) -> list:
    raws = []
    if not settings.cap_feeds:
        log.warning("CAP_FEEDS is empty, so no official alerts will be fetched. Check your .env file.")
    for feed in settings.cap_feeds:
        src = source_name(feed)
        # Skip feed items we already handled, without downloading them again.
        is_seen = (lambda g, src=src: store.feed_item_seen(src, g)) if store else None
        mark_seen = (lambda g, src=src: store.mark_feed_item(src, g)) if store else None
        try:
            raws.extend(fetch_feed(feed, source=src, is_seen=is_seen, mark_seen=mark_seen))
        except Exception as exc:
            # Log and keep going. One dead government server shouldn't
            # stop alerts from every other source.
            log.warning("Feed %s failed: %s", feed, exc)
    # Many SACHET alerts describe their area as "9 districts of Gujarat",
    # which no subscriber can match. The polygon file is the real answer.
    if settings.fetch_polygons and raws:
        add_polygons(raws)
    if settings.weather_points:
        try:
            raws.extend(fetch_rain_alerts(settings.weather_points))
        except Exception as exc:
            log.warning("Weather fetch failed: %s", exc)
    return raws


def decide_status(facts, alert_score: float, settings) -> str:
    if not facts.areas and not facts.polygons:
        # Nobody can be matched to this one, so queuing it for review only
        # wastes the reviewer's time. Keep it readable on request instead.
        return "info_only"
    if alert_score < settings.push_threshold:
        return "info_only"          # stored, available on request, not pushed
    if not settings.require_approval:
        return "approved"
    # Extreme official alerts skip the queue. Waiting 10 minutes for a human
    # during a flash flood is worse than the small risk here, because the
    # message is built only from validated fields and fixed templates.
    if facts.official and facts.severity == "Extreme":
        return "approved"
    return "pending_review"


def _ingest_one(raw, store, settings, llm, now):
    """Process one alert. Returns (facts, score, status) if it's new, else None."""
    if raw.msg_type == "Cancel":
        n = store.cancel_source_ids(raw.source, raw.references)
        log.info("Cancel from %s retired %d alert(s)", raw.source, n)
        return None

    alert_id = f"{raw.source}:{raw.source_id}"
    if store.alert_seen(alert_id):
        return None

    facts = extract_facts(raw, llm)
    if parse_iso(facts.valid_until) <= now:
        log.info("Skipping expired alert %s", alert_id)
        return None

    alert_score = score(facts)
    status = decide_status(facts, alert_score, settings)

    # An Update replaces whatever it references.
    if raw.msg_type == "Update":
        store.cancel_source_ids(raw.source, raw.references)

    store.save_alert(raw, facts, alert_score, status)
    firebase_sync.push_alert(settings.firebase_cred, facts, alert_score, status)
    for warning in facts.warnings:
        log.warning("[%s] %s", alert_id, warning)
    log.info("New alert %s: %s/%s areas=%s score=%.1f -> %s",
             alert_id, facts.hazard, facts.severity, facts.areas, alert_score, status)
    return facts, alert_score, status


def ingest(raws, store, settings, llm=None, now=None) -> list:
    now = now or now_utc()
    new = []
    for raw in raws:
        try:
            result = _ingest_one(raw, store, settings, llm, now)
        except Exception:
            # One weird alert must not block the rest. It isn't marked as
            # seen, so it'll be retried (and logged again) next cycle.
            log.exception("Failed to process alert %s:%s", raw.source, raw.source_id)
            continue
        if raw.feed_guid:
            store.mark_feed_item(raw.source, raw.feed_guid)
        if result:
            new.append(result)
    return new


def release_timed_out(store, settings) -> int:
    """If nobody reviews an OFFICIAL alert in time, send it anyway."""
    released = 0
    for row in store.pending_older_than(settings.approval_timeout_min):
        if row["source"] in ("open-meteo",):
            continue  # unofficial sources never auto-release
        store.set_status(row["alert_id"], "approved", reviewed_by="auto-timeout")
        log.warning("Auto-approved %s after %d min without review",
                    row["alert_id"], settings.approval_timeout_min)
        released += 1
    return released


def dispatch(store, sender, settings, now=None) -> int:
    now = now or now_utc()
    sent = 0
    subscribers = store.list_active_subscribers()
    for facts in store.alerts_with_status("approved"):
        for sub in subscribers:
            if not subscriber_matches(sub, facts):
                continue
            ok_to_send, reason = should_send(store, sub, facts, settings, now)
            if not ok_to_send:
                log.debug("Not sending %s to %s: %s", facts.alert_id, sub.phone, reason)
                continue
            body = render_sms(facts, sub.lang, settings.max_sms_segments)
            ok, ref = sender.send_with_retry(sub.phone, body)
            store.record_delivery(sub.phone, facts, "sms", "sent" if ok else "failed", ref, now)
            sent += int(ok)
        # The alert stays "approved" until it expires, so someone who joins
        # an hour from now still gets a warning that's still valid. Repeats
        # are prevented by the deliveries table, not by retiring the alert.
    return sent


def run_once(settings, store, sender, llm=None) -> dict:
    raws = collect_raw_alerts(settings, store)
    new = ingest(raws, store, settings, llm)
    released = release_timed_out(store, settings)
    sent = dispatch(store, sender, settings)
    summary = {"fetched": len(raws), "new": len(new), "auto_released": released, "sms_sent": sent}
    log.info("Cycle done: %s", summary)
    return summary


def run_forever(settings, store, sender, llm=None) -> None:
    log.info("CommBot polling every %ds. Ctrl+C to stop.", settings.poll_interval_sec)
    while True:
        try:
            run_once(settings, store, sender, llm)
        except Exception:
            # Never let one bad cycle kill the service. Log the full traceback.
            log.exception("Cycle crashed; will retry next interval")
        time.sleep(settings.poll_interval_sec)