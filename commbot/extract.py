"""
Turn a RawAlert into validated AlertFacts.

The golden rule of this module: an LLM is allowed to *pick* from fixed lists
and to *copy* text that's really in the source. It is never allowed to write
the warning itself. Everything it returns gets checked against the original
text, and anything that can't be found there is thrown away.

Why so strict? A hallucinated helpline number or shelter name during a flood
can send people the wrong way. Boring and correct beats clever and wrong.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from .models import AlertFacts, RawAlert
from .utils import now_utc, parse_iso, to_iso

log = logging.getLogger(__name__)

# Order matters in both lists: it's the order things appear in messages.
HAZARDS = ["FLOOD", "CYCLONE", "EARTHQUAKE", "LANDSLIDE", "HEAVY_RAIN",
           "THUNDERSTORM", "HEATWAVE", "COLD_WAVE", "OTHER"]

ACTIONS = ["EVACUATE", "DROP_COVER", "MOVE_HIGHER", "AVOID_WATER", "STAY_INDOORS",
           "AVOID_TREES_POLES", "AVOID_TRAVEL", "SAFE_WATER", "HYDRATE", "KEEP_ESSENTIALS",
           "FOLLOW_OFFICIALS"]

SEVERITIES = ["Extreme", "Severe", "Moderate", "Minor", "Unknown"]

# Keyword rules, English + Hindi. Deliberately simple so a non-programmer
# volunteer can add words without touching the logic.
HAZARD_KEYWORDS = {
    "FLOOD": ["flood", "inundat", "danger mark", "à¤¬à¤¾à¤¢à¤¼", "à¤œà¤²à¤­à¤°à¤¾à¤µ"],
    "CYCLONE": ["cyclone", "à¤šà¤•à¥à¤°à¤µà¤¾à¤¤"],
    "EARTHQUAKE": ["earthquake", "tremor", "à¤­à¥‚à¤•à¤‚à¤ª"],
    "LANDSLIDE": ["landslide", "à¤­à¥‚à¤¸à¥à¤–à¤²à¤¨"],
    "HEAVY_RAIN": ["heavy rain", "rainfall", "à¤­à¤¾à¤°à¥€ à¤¬à¤¾à¤°à¤¿à¤¶", "à¤­à¤¾à¤°à¥€ à¤µà¤°à¥à¤·à¤¾"],
    "THUNDERSTORM": ["thunderstorm", "lightning", "à¤µà¤œà¥à¤°à¤ªà¤¾à¤¤", "à¤†à¤•à¤¾à¤¶à¥€à¤¯ à¤¬à¤¿à¤œà¤²à¥€", "à¤†à¤‚à¤§à¥€"],
    "HEATWAVE": ["heat wave", "heatwave", "à¤²à¥‚"],
    "COLD_WAVE": ["cold wave", "à¤¶à¥€à¤¤à¤²à¤¹à¤°"],
}

ACTION_KEYWORDS = {
    "EVACUATE": ["evacuat", "relocate", "move to relief camp", "à¤–à¤¾à¤²à¥€ à¤•à¤°", "à¤°à¤¾à¤¹à¤¤ à¤¶à¤¿à¤µà¤¿à¤° à¤®à¥‡à¤‚"],
    "DROP_COVER": ["drop, cover", "drop cover", "take cover under"],
    "MOVE_HIGHER": ["higher ground", "higher place", "à¤Šà¤à¤šà¥‡ à¤¸à¥à¤¥à¤¾à¤¨", "à¤Šà¤‚à¤šà¥‡ à¤¸à¥à¤¥à¤¾à¤¨"],
    "AVOID_WATER": ["cross the river", "flooded road", "stay away from river",
                    "avoid river", "do not enter water", "à¤¨à¤¦à¥€", "à¤¨à¤¾à¤²à¥‹à¤‚"],
    "STAY_INDOORS": ["stay indoors", "remain indoors", "avoid going out", "à¤˜à¤° à¤•à¥‡ à¤…à¤‚à¤¦à¤°", "à¤¬à¤¾à¤¹à¤° à¤¨ à¤¨à¤¿à¤•à¤²à¥‡à¤‚"],
    "AVOID_TREES_POLES": ["under trees", "electric pole", "à¤ªà¥‡à¤¡à¤¼ à¤•à¥‡ à¤¨à¥€à¤šà¥‡", "à¤¬à¤¿à¤œà¤²à¥€ à¤•à¥‡ à¤–à¤‚à¤­"],
    "AVOID_TRAVEL": ["avoid travel", "avoid unnecessary travel", "à¤¯à¤¾à¤¤à¥à¤°à¤¾ à¤¨"],
    "SAFE_WATER": ["boil", "safe drinking water", "à¤‰à¤¬à¤¾à¤²"],
    "HYDRATE": ["drink plenty of water", "stay hydrated", "à¤ªà¤¾à¤¨à¥€ à¤ªà¥€à¤¤à¥‡ à¤°à¤¹à¥‡à¤‚", "à¤–à¥‚à¤¬ à¤ªà¤¾à¤¨à¥€"],
    "KEEP_ESSENTIALS": ["documents", "medicines", "emergency kit", "torch", "à¤¦à¤¸à¥à¤¤à¤¾à¤µà¥‡à¤œ"],
    "FOLLOW_OFFICIALS": ["follow instructions", "follow the advice", "guidelines", "advisory",
                         "à¤ªà¥à¤°à¤¶à¤¾à¤¸à¤¨ à¤•à¥‡ à¤¨à¤¿à¤°à¥à¤¦à¥‡à¤¶", "à¤¦à¤¿à¤¶à¤¾à¤¨à¤¿à¤°à¥à¤¦à¥‡à¤¶"],
}

# Nationally known short codes. 112 is India's single emergency number,
# 1070/1077 are the usual state/district disaster control rooms.
KNOWN_SHORT_CODES = {"100", "101", "102", "108", "112", "1070", "1077", "1078"}

# areaDesc values that don't name a real place. SACHET uses "some parts" a lot.
VAGUE_AREAS = {"some parts", "some places", "few places", "a few places", "isolated places",
               "many places", "most places", "parts", "some areas", "state", "district", "na", "-",
               "mod tsra", "tsra", "mts", "mod rain with mts", "rain with mts"}  # TSRA is aviation code for thunderstorm+rain, not a place

# "9 districts of Gujarat", "6 Mandals": a count, not a name. Real SACHET data
# is full of these, and no subscriber can ever be matched to them.
COUNT_ONLY_AREA_RE = re.compile(
    r"^\s*\d+\s+(districts?|mandals?|taluks?|tehsils?|blocks?|places?|areas?)\b", re.IGNORECASE)

# "Idukki,Kottayam districts of Kerala" -> "Idukki,Kottayam"
# "mkp-kanigiri, mkp-veligandla mandals"  -> "mkp-kanigiri, mkp-veligandla"
# The state name and the word "district" only pad out an SMS that has to fit
# in 70 Hindi characters, and translating them mid-sentence reads badly.
AREA_SUFFIX_RE = re.compile(
    r"\s+(?:districts?|mandals?|taluks?|tehsils?|blocks?)\b(?:\s+(?:of|in)\s+.+)?$",
    re.IGNORECASE)

RELIEF_RE = re.compile(r"relief camps? (?:at|in) ([^.;\n]+)", re.IGNORECASE)

SYSTEM_PROMPT = f"""You extract facts from official disaster alerts.
Reply with ONE JSON object and nothing else. No markdown, no explanation.

Rules:
- Use ONLY information stated in the alert text. Never guess. Never add advice.
- If something is not mentioned, use an empty list or "Unknown".
- Copy place names and shelter names exactly as written. Do not translate them.
- Copy phone numbers digit for digit.

JSON keys:
  "hazard":    one of {HAZARDS}
  "severity":  one of {SEVERITIES}
  "areas":     list of districts / tehsils / villages mentioned
  "actions":   list chosen ONLY from {ACTIONS}
  "helplines": list of phone numbers
  "shelters":  list of relief camp or shelter names/locations
"""

USER_TEMPLATE = "ALERT TEXT:\n<<<\n{text}\n>>>"


# ---------------------------------------------------------------------------
# Rule-based helpers
# ---------------------------------------------------------------------------

def guess_hazard(raw: RawAlert) -> str:
    # The CAP <event> field is the most reliable, so check it first,
    # then the headline, then the body.
    for chunk in (raw.event, raw.title, raw.body):
        text = (chunk or "").casefold()
        for hazard, words in HAZARD_KEYWORDS.items():
            if any(w in text for w in words):
                return hazard
    return "OTHER"


def guess_actions(text: str) -> list[str]:
    lowered = text.casefold()
    return [a for a, words in ACTION_KEYWORDS.items() if any(w in lowered for w in words)]


def is_vague_area(area: str) -> bool:
    if COUNT_ONLY_AREA_RE.match(area or ""):
        return True
    cleaned = re.sub(r"[^a-z ]", " ", area.casefold()).strip()
    cleaned = " ".join(cleaned.split())
    return len(cleaned) < 3 or cleaned in VAGUE_AREAS


def tidy_area(area: str) -> str:
    trimmed = AREA_SUFFIX_RE.sub("", (area or "").strip()).strip(" ,")
    # Feeds write "Idukki,Kottayam"; on a phone that reads better spaced out.
    return re.sub(r"\s*,\s*", ", ", trimmed)


def areas_from_text(text: str) -> list[str]:
    """
    Pull district names out of sentences like
    "...likely to affect over some parts of East Midnapore, West Midnapore districts..."
    -> ["East Midnapore", "West Midnapore"]

    Only used when the CAP area field is useless. Deliberately conservative:
    it only fires on the word "district(s)" and wants Capitalised names.
    """
    names = []
    # No digits allowed in the match, so it can't run back across "30-40 kmph".
    for match in re.finditer(r"([A-Za-z][A-Za-z .,&'-]{2,200}?)\s+districts?\b", text):
        chunk = match.group(1)
        # Keep only what comes after the last "of" / "over" / "in" etc.
        chunk = re.split(r"\b(?:of|over|in|at|across|covering)\b", chunk, flags=re.IGNORECASE)[-1]
        for part in re.split(r",|\band\b|&", chunk):
            part = part.strip(" .")
            if part and part[0].isupper() and len(part) <= 40 and not is_vague_area(part):
                names.append(part)
    return list(dict.fromkeys(names))


def _looks_like_phone(digits: str) -> bool:
    if digits in KNOWN_SHORT_CODES:
        return True
    if len(digits) == 10 and digits[0] in "6789":        # mobile
        return True
    if len(digits) == 11 and digits[0] == "0":           # landline with STD code
        return True
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return True
    return False


def _normalize_phone(digits: str) -> str:
    return digits[2:] if len(digits) == 12 and digits.startswith("91") else digits


def extract_phone_numbers(text: str) -> list[str]:
    """
    Find phone numbers without swallowing dates, years or rainfall numbers.
    Handles "1077", "05252-000000" and "+91 98765 43210".
    """
    tokens = [(m.start(), m.end(), re.sub(r"\D", "", m.group()))
              for m in re.finditer(r"\+?\d+(?:-\d+)*", text)]
    found, i = [], 0
    while i < len(tokens):
        start, end, digits = tokens[i]
        # Try gluing space-separated chunks: "98765 43210" -> "9876543210"
        merged, j, merged_end = digits, i, end
        while (j + 1 < len(tokens) and tokens[j + 1][0] == merged_end + 1
               and text[merged_end] == " " and len(merged + tokens[j + 1][2]) <= 12):
            merged += tokens[j + 1][2]
            merged_end = tokens[j + 1][1]
            j += 1
        if j > i and _looks_like_phone(merged):
            found.append(_normalize_phone(merged))
            i = j + 1
        else:
            if _looks_like_phone(digits):
                found.append(_normalize_phone(digits))
            i += 1
    return list(dict.fromkeys(found))  # dedupe, keep order


def _parse_json_reply(reply: str) -> dict | None:
    if not reply:
        return None
    cleaned = reply.replace("```json", "").replace("```", "")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_facts(raw: RawAlert, llm=None) -> AlertFacts:
    text = raw.full_text()
    lowered = text.casefold()
    warnings: list[str] = []

    # 1) Start with what we can get deterministically.
    hazard = guess_hazard(raw)
    actions = guess_actions(f"{raw.instruction} {raw.body}")
    helplines = extract_phone_numbers(text)
    shelters = [m.strip() for m in RELIEF_RE.findall(text)]
    areas = [tidy_area(a) for a in raw.areas if not is_vague_area(a)]
    areas = [a for a in areas if a]
    if not areas:
        # e.g. SACHET's areaDesc "some parts": the real districts are only
        # named in the headline, so dig them out of the text instead.
        areas = areas_from_text(f"{raw.title} {raw.body}")
        if areas:
            warnings.append(f"Vague area {raw.areas!r}; took districts from text: {areas}")
        elif not raw.polygons:
            warnings.append("No usable area or polygon: no subscriber can be matched to this alert")
    severity = raw.severity if raw.severity in SEVERITIES else "Unknown"
    method = "rules"

    # 2) Let the LLM fill gaps, then verify everything it says.
    if llm is not None:
        data = _parse_json_reply(llm.complete(SYSTEM_PROMPT, USER_TEMPLATE.format(text=text[:6000])))
        if data is None:
            warnings.append("LLM reply unusable, used keyword rules only")
        else:
            method = "llm"

            # Only accept the LLM's hazard if our rules had nothing better.
            llm_hazard = str(data.get("hazard", "")).upper()
            if hazard == "OTHER" and llm_hazard in HAZARDS:
                hazard = llm_hazard

            # CAP's own severity always wins. LLM only fills an Unknown.
            if severity == "Unknown" and data.get("severity") in SEVERITIES:
                severity = data["severity"]

            for action in _as_list(data.get("actions")):
                if action in ACTIONS and action not in actions:
                    actions.append(action)

            for area in _as_list(data.get("areas")):
                if area.casefold() in lowered:
                    if area not in areas and not any(area.casefold() in a.casefold() for a in areas):
                        areas.append(area)
                else:
                    warnings.append(f"Dropped area not found in source: {area!r}")

            # Our regex already finds every real number in the text, so any
            # number the LLM returns that we *didn't* find is made up.
            for phone in _as_list(data.get("helplines")):
                digits = _normalize_phone(re.sub(r"\D", "", phone))
                if digits not in helplines:
                    warnings.append(f"Dropped helpline not found in source: {phone!r}")

            for shelter in _as_list(data.get("shelters")):
                if shelter.casefold() in lowered:
                    if not any(shelter.casefold() in s.casefold() or s.casefold() in shelter.casefold()
                               for s in shelters):
                        shelters.append(shelter)
                else:
                    warnings.append(f"Dropped shelter not found in source: {shelter!r}")

    # 3) Safety guard: telling people to evacuate when the official alert
    #    didn't say so can cause panic and traffic jams on escape routes.
    evac_words = ACTION_KEYWORDS["EVACUATE"]
    if "EVACUATE" in actions and not any(w in lowered for w in evac_words):
        actions.remove("EVACUATE")
        warnings.append("Removed EVACUATE: source text never says to evacuate")

    actions = sorted(set(actions), key=ACTIONS.index)

    # 4) Validity window. Default to 12h if the source didn't give one.
    expires = parse_iso(raw.expires)
    if expires is None:
        base = parse_iso(raw.sent) or now_utc()
        expires = base + timedelta(hours=12)
        warnings.append("No expiry in source; assumed 12 hours")

    return AlertFacts(
        alert_id=f"{raw.source}:{raw.source_id}",
        hazard=hazard,
        severity=severity,
        urgency=raw.urgency,
        certainty=raw.certainty,
        areas=areas,
        actions=actions,
        helplines=helplines,
        shelters=shelters,
        valid_until=to_iso(expires),
        headline=raw.title or raw.event,
        source_name=raw.sender_name,
        official=raw.official,
        polygons=raw.polygons,
        circles=raw.circles,
        extraction_method=method,
        warnings=warnings,
    )
