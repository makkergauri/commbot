"""
Heavy-rain early warning from the Open-Meteo forecast API (free, no key).

IMPORTANT: this is a *model forecast*, not an official warning. We mark these
alerts official=False, which means the decision agent never pushes them as
SMS on their own. They're only available when someone asks (STATUS or a
phone call). Official IMD/NDMA warnings always win.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from ..models import RawAlert
from ..utils import IST, now_utc, to_iso

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# IMD's 24-hour rainfall categories (mm). Using the same thresholds as IMD
# means our wording lines up with what people hear on the news.
RAIN_CATEGORIES = [
    (204.5, "Extremely heavy rain", "Extreme"),
    (115.6, "Very heavy rain", "Severe"),
    (64.5, "Heavy rain", "Moderate"),
]


def classify_rain(mm: float):
    for threshold, label, severity in RAIN_CATEGORIES:
        if mm >= threshold:
            return label, severity
    return None


def fetch_rain_alerts(points, days: int = 3, session=None) -> list[RawAlert]:
    http = session or requests
    alerts = []
    for lat, lon, name in points:
        try:
            resp = http.get(OPEN_METEO_URL, timeout=15, params={
                "latitude": lat,
                "longitude": lon,
                "daily": "precipitation_sum",
                "timezone": "Asia/Kolkata",
                "forecast_days": days,
            })
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
        except (requests.RequestException, ValueError) as exc:
            log.warning("Weather fetch failed for %s: %s", name, exc)
            continue

        for day, mm in zip(daily.get("time", []), daily.get("precipitation_sum", [])):
            if mm is None:
                continue
            result = classify_rain(mm)
            if not result:
                continue
            label, severity = result
            day_end = datetime.fromisoformat(day).replace(tzinfo=IST) + timedelta(days=1)
            alerts.append(RawAlert(
                source="open-meteo",
                source_id=f"{name}-{day}-{label}".replace(" ", "_"),
                title=f"{label} forecast for {name}",
                body=f"Model forecast: about {mm:.0f} mm of rain expected in {name} on {day}.",
                event="Heavy Rain",
                sender_name="Open-Meteo forecast",
                severity=severity,
                urgency="Expected",
                certainty="Likely",
                areas=[name],
                sent=to_iso(now_utc()),
                expires=to_iso(day_end),
                official=False,
            ))
    return alerts
