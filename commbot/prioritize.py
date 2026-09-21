"""
The decision agent: how urgent is this alert, who should get it, and should
we message this particular person right now?

This is intentionally rule-based and explainable. When a district officer
asks "why did my village get this at 3am?", you need a clear answer, not
"the model felt like it". Every decision returns a reason string that ends
up in the logs.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from .geo import area_matches, haversine_km, normalize_place, point_in_polygon
from .models import AlertFacts, Subscriber
from .utils import parse_iso

SEVERITY_RANK = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1, "Unknown": 1}
URGENCY_WEIGHT = {"Immediate": 3, "Expected": 2, "Future": 1, "Past": 0, "Unknown": 1}
CERTAINTY_WEIGHT = {"Observed": 1.0, "Likely": 0.8, "Possible": 0.5, "Unlikely": 0.2, "Unknown": 0.6}


def score(facts: AlertFacts) -> float:
    """
    Score from 0 to 12. With the default push threshold of 6:
      Severe  + Expected  + Observed  -> 6.0 (pushed)
      Severe  + Immediate + Likely    -> 7.2 (pushed)
      Moderate+ Expected  + Likely    -> 3.2 (only on request)
    Unofficial sources get a 0.6 multiplier, which keeps model forecasts
    below the push line on their own.
    """
    trust = 1.0 if facts.official else 0.6
    raw = (SEVERITY_RANK.get(facts.severity, 1)
           * URGENCY_WEIGHT.get(facts.urgency, 1)
           * CERTAINTY_WEIGHT.get(facts.certainty, 0.6)
           * trust)
    return round(raw, 2)


def fingerprint(facts: AlertFacts) -> str:
    # Same hazard for the same areas = "same story", even if the source
    # re-issued it with a new id. Used to avoid spamming people.
    key = facts.hazard + "|" + "|".join(sorted(normalize_place(a) for a in facts.areas))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def subscriber_matches(sub: Subscriber, facts: AlertFacts) -> bool:
    # Exact location beats names, when we have it.
    if sub.lat is not None and sub.lon is not None:
        if any(point_in_polygon(sub.lat, sub.lon, poly) for poly in facts.polygons):
            return True
        if any(haversine_km(sub.lat, sub.lon, c[0], c[1]) <= c[2] for c in facts.circles):
            return True
    return area_matches(sub.district, facts.areas)


def should_send(store, sub: Subscriber, facts: AlertFacts, settings, now) -> tuple[bool, str]:
    rank = SEVERITY_RANK.get(facts.severity, 1)

    if store.was_delivered(sub.phone, facts.alert_id):
        return False, "already delivered"

        
    ends = parse_iso(facts.valid_until)
    if ends and ends - now < timedelta(minutes=settings.min_minutes_left):
        return False, "too close to expiry to be useful"
    

    last = store.last_delivery(sub.phone, fingerprint(facts))
    if last:
        age = now - parse_iso(last["sent_at"])
        # Re-send the same story only if it got WORSE (e.g. Severe -> Extreme).
        # NOTE: an Update with new details but the same severity gets
        # suppressed here. People can still get it via STATUS or a call.
        if age < timedelta(minutes=settings.resend_cooldown_min) and rank <= last["severity_rank"]:
            return False, "same alert sent recently"

    # Rate limit to avoid alert fatigue, but never hold back Extreme alerts.
    if rank < 4:
        recent = store.count_deliveries_since(sub.phone, now - timedelta(hours=1))
        if recent >= settings.max_sms_per_hour:
            return False, "hourly limit reached"

    return True, "ok"
