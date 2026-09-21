"""
Ingest Common Alerting Protocol (CAP) alerts.

Why CAP instead of scraping websites? CAP is the international standard for
public warnings, and India's NDMA publishes alerts in CAP via the SACHET
platform. That means the government has *already* told us the severity,
urgency and exact area in a machine-readable way. We trust those fields far
more than anything an LLM guesses from free text.

Handles three kinds of input:
  1. a single CAP XML document
  2. an RSS/Atom feed whose items link to CAP documents
  3. a local file path (great for demos and offline testing)
"""
from __future__ import annotations

import logging
import math
import time
import xml.etree.ElementTree as ET

import requests

from ..models import RawAlert
from ..utils import now_utc, parse_iso

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "CommBot/0.1 (open-source crisis alert relay)"}
TIMEOUT = 15
MAX_ITEMS_PER_FEED = 50


def _strip_ns(root: ET.Element) -> ET.Element:
    # CAP 1.1 and 1.2 use different namespaces, and some feeds skip the
    # namespace entirely. Stripping them lets one code path handle all three.
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(el: ET.Element, tag: str, default: str = "") -> str:
    child = el.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _parse_polygon(text: str) -> list[tuple[float, float]]:
    # CAP polygons are space-separated "lat,lon" pairs.
    points = []
    for pair in text.split():
        try:
            lat, lon = pair.split(",")[:2]
            points.append((float(lat), float(lon)))
        except ValueError:
            continue  # skip one bad point instead of dropping the whole alert
    return points if len(points) >= 3 else []


def _parse_circle(text: str):
    # Format is "lat,lon radius_km"
    try:
        center, radius = text.split()
        lat, lon = center.split(",")
        return (float(lat), float(lon), float(radius))
    except ValueError:
        return None


def _pick_info(infos: list[ET.Element]) -> ET.Element:
    # One alert can carry the same message in several languages. We extract
    # from English when it's there (our keyword rules and most open LLMs are
    # strongest in English) and fall back to whatever comes first.
    for info in infos:
        if _text(info, "language", "en").lower().startswith("en"):
            return info
    return infos[0]


def parse_cap(xml_text, source: str = "cap", allow_non_actual: bool = False) -> list[RawAlert]:
    """Turn one CAP XML document into RawAlert objects (usually exactly one)."""
    root = _strip_ns(ET.fromstring(xml_text))
    if root.tag != "alert":
        raise ValueError(f"Not a CAP document (root is <{root.tag}>)")

    status = _text(root, "status", "Actual")
    if status != "Actual" and not allow_non_actual:
        # Exercises, tests and drafts must never reach real phones.
        log.info("Skipping CAP alert with status=%s", status)
        return []

    identifier = _text(root, "identifier")
    msg_type = _text(root, "msgType", "Alert")

    # <references> is "sender,identifier,sent sender,identifier,sent ..."
    # We only need the identifiers to know which older alerts to retire.
    refs = []
    for ref in _text(root, "references").split():
        parts = ref.split(",")
        if len(parts) >= 2:
            refs.append(parts[1])

    infos = root.findall("info")
    if not infos:
        # A Cancel message is allowed to have no <info> block at all.
        return [RawAlert(source=source, source_id=identifier, msg_type=msg_type,
                         references=refs, sent=_text(root, "sent"))]

    info = _pick_info(infos)

    areas, polygons, circles = [], [], []
    for area in info.findall("area"):
        desc = _text(area, "areaDesc")
        if desc:
            areas.append(desc)
        for poly in area.findall("polygon"):
            pts = _parse_polygon(poly.text or "")
            if pts:
                polygons.append(pts)
        for circle in area.findall("circle"):
            parsed = _parse_circle(circle.text or "")
            if parsed:
                circles.append(parsed)

    # SACHET puts extras here, e.g. valueName "Polygon URL".
    parameters = {}
    for param in info.findall("parameter"):
        name = _text(param, "valueName")
        if name:
            parameters[name] = _text(param, "value")

    return [RawAlert(
        source=source,
        source_id=identifier,
        title=_text(info, "headline"),
        body=_text(info, "description"),
        instruction=_text(info, "instruction"),
        event=_text(info, "event"),
        sender_name=_text(info, "senderName") or _text(root, "sender"),
        severity=_text(info, "severity", "Unknown"),
        urgency=_text(info, "urgency", "Unknown"),
        certainty=_text(info, "certainty", "Unknown"),
        areas=areas,
        polygons=polygons,
        circles=circles,
        sent=_text(root, "sent"),
        expires=_text(info, "expires"),
        language=_text(info, "language", "en"),
        msg_type=msg_type,
        references=refs,
        official=True,
        parameters=parameters,
    )]


# Remember ETag / Last-Modified per URL so we can ask the server "has this
# changed?" instead of downloading the whole feed every poll. SACHET's feed
# guide asks integrators to do this.
_http_cache: dict[str, dict] = {}

POLITE_DELAY_SEC = 0.3  # pause between per-alert downloads; it's a government server


def _load(url_or_path: str, use_cache: bool = False) -> bytes:
    if url_or_path.startswith("file://"):
        path = url_or_path[len("file://"):]
    elif not url_or_path.startswith(("http://", "https://")):
        path = url_or_path
    else:
        headers = dict(HEADERS)
        cached = _http_cache.get(url_or_path) if use_cache else None
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        resp = requests.get(url_or_path, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 304 and cached:
            # Nothing changed since last time. Reuse what we had.
            return cached["content"]
        resp.raise_for_status()
        if use_cache:
            _http_cache[url_or_path] = {
                "etag": resp.headers.get("ETag"),
                "last_modified": resp.headers.get("Last-Modified"),
                "content": resp.content,
            }
        return resp.content
    with open(path, "rb") as fh:
        return fh.read()


def _feed_items(root: ET.Element) -> list[tuple[str, str]]:
    """Return (guid, link) pairs from an RSS or Atom feed."""
    items = []
    for item in root.iter("item"):                      # RSS
        link = _text(item, "link")
        if link:
            items.append((_text(item, "guid"), link))
    for entry in root.iter("entry"):                    # Atom
        for l in entry.findall("link"):
            if l.get("href"):
                items.append((_text(entry, "id"), l.get("href")))
    return items


def fetch_feed(url: str, source: str = "cap", is_seen=None, mark_seen=None) -> list[RawAlert]:
    """
    Fetch a CAP document or an RSS/Atom feed of CAP documents.

    is_seen(guid) -> bool lets the caller skip feed items it already handled,
    so we don't re-download the same XML every poll.

    Careful: on SACHET the RSS <guid> ("1789916877126017") is NOT the CAP
    <identifier> ("IN-1789916877126017_17"). So we track feed items by guid
    separately from alerts. Each RawAlert carries its feed_guid, and the
    pipeline marks it seen only after the alert is safely stored.
    """
    content = _load(url, use_cache=True)
    root = _strip_ns(ET.fromstring(content))

    if root.tag == "alert":
        return parse_cap(content, source)

    alerts, skipped = [], 0
    for guid, link in _feed_items(root)[:MAX_ITEMS_PER_FEED]:
        if guid and is_seen and is_seen(guid):
            skipped += 1
            continue
        try:
            parsed = parse_cap(_load(link), source)
        except (requests.RequestException, ET.ParseError, ValueError, OSError) as exc:
            # Not marked as seen, so we'll try again next poll.
            log.warning("Couldn't read CAP item %s: %s", link, exc)
            parsed = None
        if parsed is not None:
            if not parsed and guid and mark_seen:
                mark_seen(guid)  # e.g. an Exercise alert: nothing to store, don't refetch
            for alert in parsed:
                alert.feed_guid = guid
            alerts.extend(parsed)
        if link.startswith("http"):
            time.sleep(POLITE_DELAY_SEC)
    log.info("Feed %s: %d new item(s) fetched, %d already known", url, len(alerts), skipped)
    return alerts


# Real SACHET polygons can carry 60,000+ points for one alert. Matching a
# subscriber's GPS against that on every cycle is slow and bloats the
# database, and at district scale a few hundred points loses nothing.
MAX_POLYGON_POINTS = 400


def thin_polygon(points: list, limit: int = MAX_POLYGON_POINTS) -> list:
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    thinned = points[::step]
    if thinned[-1] != points[-1]:
        thinned.append(points[-1])  # keep the ring closed
    return thinned


def fetch_polygon(url: str) -> list:
    """
    Fetch SACHET's separate polygon file.

    It looks like a mini CAP document: <alert><identifier/><polygon>lat,lon
    lat,lon ...</polygon></alert>. Real files sometimes have two points glued
    together with a missing space; _parse_polygon drops those points rather
    than losing the whole shape.
    """
    root = _strip_ns(ET.fromstring(_load(url)))
    polygons = []
    for el in root.iter("polygon"):
        points = _parse_polygon(el.text or "")
        if points:
            polygons.append(thin_polygon(points))
    return polygons


def add_polygons(alerts: list, max_fetches: int = 25) -> list:
    """
    Fill in geometry for alerts that have a Polygon URL but no inline polygon.

    Capped per cycle so a busy feed can't turn into hundreds of requests to a
    government server. Anything not fetched this time is still targeted by
    district name, and will be picked up if it's re-processed.
    """
    fetched, now = 0, now_utc()
    for alert in alerts:
        if alert.polygons or fetched >= max_fetches:
            continue
        # Don't spend a request on a shape for an alert that's already over.
        expires = parse_iso(alert.expires)
        if expires and expires <= now:
            continue
        url = next((v for k, v in alert.parameters.items()
                    if k.strip().casefold() == "polygon url" and v), "")
        if not url:
            continue
        try:
            polygons = fetch_polygon(url)
        except (requests.RequestException, ET.ParseError, ValueError, OSError) as exc:
            log.warning("Polygon fetch failed for %s: %s", alert.source_id, exc)
            continue
        fetched += 1
        if polygons:
            alert.polygons = polygons
            log.info("Got %d polygon(s), %d points, for %s",
                     len(polygons), sum(len(p) for p in polygons), alert.source_id)
        if url.startswith("http"):
            time.sleep(POLITE_DELAY_SEC)
    return alerts