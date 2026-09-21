"""
Multilingual message rendering.

Messages are assembled from reviewed phrase templates, one set per language.
We do NOT machine-translate warnings on the fly. A bad translation of "move
to higher ground" is a safety problem, so every phrase here should be checked
by a native speaker before it goes live.

Adding a language = copy the "en" block, translate it, get it reviewed,
add the code to SUPPORTED_LANGS. That's it.
"""
from __future__ import annotations

import math

from .models import AlertFacts
from .utils import fmt_local

SUPPORTED_LANGS = ("hi", "en")

TEMPLATES = {
    "en": {
        "brand": "CommBot",
        "warning": "warning",
        "advisory": "advisory",
        "camp": "Relief camp: {camp}",
        "forecast_tag": "(forecast)",
        "sep": ". ",
        "hazards": {
            "FLOOD": "Flood", "HEAVY_RAIN": "Heavy rain", "CYCLONE": "Cyclone",
            "EARTHQUAKE": "Earthquake", "THUNDERSTORM": "Thunderstorm/lightning",
            "HEATWAVE": "Heatwave", "COLD_WAVE": "Cold wave", "LANDSLIDE": "Landslide",
            "OTHER": "Emergency",
        },
        "severity": {"Extreme": "EXTREME ", "Severe": "SEVERE "},
        "actions": {
            "EVACUATE": "Evacuate to the nearest relief camp now",
            "DROP_COVER": "Drop, cover and hold on",
            "MOVE_HIGHER": "Move to higher ground",
            "AVOID_WATER": "Stay away from rivers and flood water",
            "STAY_INDOORS": "Stay indoors",
            "AVOID_TREES_POLES": "Keep away from trees and electric poles",
            "AVOID_TRAVEL": "Avoid unnecessary travel",
            "SAFE_WATER": "Drink only boiled or safe water",
            "HYDRATE": "Drink plenty of water",
            "KEEP_ESSENTIALS": "Keep documents, medicines and a torch ready",
            "FOLLOW_OFFICIALS": "Follow instructions from officials",
        },
        "call": "Helpline {phones}",
        "until": "Valid till {time}",
        "source": "Source: {src}",
        # Long form, used when someone texts STATUS and asks what's happening
        "summary": "{sev}{hazard} warning for {areas}. {actions}. For help, call {phones}. This information is from {src}.",
        # Q&A and SMS replies
        "no_alert": "There is no active official alert for {area} right now. In an emergency, call 112.",
        "shelter": "Relief camp information: {shelters}.",
        "no_shelter": "The official alert does not name a relief camp. Call {phones} for the nearest one.",
        "helpline": "Helpline numbers: {phones}. National emergency number: 112.",
        "unknown": "Sorry, I can only share official alert information. In an emergency, call 112.",
        "joined": "You are subscribed to CommBot alerts for {district}. Send STATUS for current alerts, STOP to unsubscribe.",
        "stopped": "You will no longer get CommBot alerts. Send JOIN <district> to rejoin.",
        "help": "Commands: JOIN <district> [HI/EN], STATUS, SHELTER, HELPLINE, STOP. Emergency: 112",
        "need_district": "Please send JOIN followed by your district, e.g. JOIN Bahraich",
        "unregistered": "To get alerts for your area, send an SMS: JOIN followed by your district name.",
    },
    "hi": {
        "brand": "CommBot",
        "warning": "चेतावनी",
        "advisory": "सलाह",
        "camp": "राहत शिविर: {camp}",
        "forecast_tag": "(पूर्वानुमान)",
        "sep": "। ",
        "hazards": {
            "FLOOD": "बाढ़", "HEAVY_RAIN": "भारी बारिश", "CYCLONE": "चक्रवात",
            "EARTHQUAKE": "भूकंप", "THUNDERSTORM": "आंधी/बिजली", "HEATWAVE": "लू",
            "COLD_WAVE": "शीतलहर", "LANDSLIDE": "भूस्खलन", "OTHER": "आपदा",
        },
        "severity": {"Extreme": "अत्यंत गंभीर ", "Severe": "गंभीर "},
        "actions": {
            "EVACUATE": "तुरंत नज़दीकी राहत शिविर में जाएं",
            "DROP_COVER": "झुकें, सिर ढकें और पकड़ कर रखें",
            "MOVE_HIGHER": "ऊँचे स्थान पर जाएं",
            "AVOID_WATER": "नदी-नालों और बाढ़ के पानी से दूर रहें",
            "STAY_INDOORS": "घर के अंदर रहें",
            "AVOID_TREES_POLES": "पेड़ों और बिजली के खंभों से दूर रहें",
            "AVOID_TRAVEL": "अनावश्यक यात्रा न करें",
            "SAFE_WATER": "केवल उबला या साफ पानी पिएं",
            "HYDRATE": "खूब पानी पिएं",
            "KEEP_ESSENTIALS": "ज़रूरी दस्तावेज, दवाएं और टॉर्च तैयार रखें",
            "FOLLOW_OFFICIALS": "प्रशासन के निर्देशों का पालन करें",
        },
        "call": "हेल्पलाइन {phones}",
        "until": "{time} तक मान्य",
        "source": "स्रोत: {src}",
        "summary": "{areas} के लिए {sev}{hazard} की चेतावनी है। {actions}। मदद के लिए {phones} पर कॉल करें। यह जानकारी {src} से है।",
        "no_alert": "{area} के लिए अभी कोई सक्रिय सरकारी चेतावनी नहीं है। आपात स्थिति में 112 पर कॉल करें।",
        "shelter": "राहत शिविर की जानकारी: {shelters}।",
        "no_shelter": "सरकारी सूचना में राहत शिविर का नाम नहीं है। नज़दीकी शिविर के लिए {phones} पर कॉल करें।",
        "helpline": "हेल्पलाइन नंबर: {phones}। राष्ट्रीय आपातकालीन नंबर 112 है।",
        "unknown": "क्षमा करें, मैं केवल सरकारी चेतावनी की जानकारी दे सकता हूँ। आपात स्थिति में 112 पर कॉल करें।",
        "joined": "आप {district} की कॉमबॉट सूचनाओं से जुड़ गए हैं। वर्तमान सूचना के लिए STATUS और बंद करने के लिए STOP भेजें।",
        "stopped": "अब आपको कॉमबॉट सूचनाएं नहीं मिलेंगी। दोबारा जुड़ने के लिए JOIN <जिला> भेजें।",
        "help": "कमांड: JOIN <जिला> [HI/EN], STATUS, SHELTER, HELPLINE, STOP। आपातकाल: 112",
        "need_district": "कृपया JOIN के बाद अपने जिले का नाम भेजें, जैसे JOIN Bahraich",
        "unregistered": "अपने क्षेत्र की सूचना पाने के लिए SMS भेजें: JOIN और अपने जिले का नाम।",
    },
}

# Tiny gazetteer so Hindi messages don't show English place names.
# TODO: replace with a proper district/tehsil list, or AI4Bharat IndicXlit
# for automatic transliteration (and still have someone spot-check it).
PLACE_NAMES_HI = {
    "bahraich": "बहराइच", "shravasti": "श्रावस्ती", "gonda": "गोंडा",
    "lakhimpur kheri": "लखीमपुर खीरी", "sitapur": "सीतापुर", "barabanki": "बाराबंकी",
    "gorakhpur": "गोरखपुर", "pilibhit": "पीलीभीत", "lucknow": "लखनऊ",
    "mahsi": "महसी", "kaiserganj": "कैसरगंज",
}

# GSM-7 basic character set. If every character is in here, one SMS holds 160
# characters. One Hindi (or emoji) character switches the whole message to
# UCS-2 and you only get 70. That's why Hindi alerts must be short.
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)


def lang_or_default(lang: str | None, default: str = "hi") -> str:
    lang = (lang or "").lower()[:2]
    return lang if lang in TEMPLATES else default


def t(lang: str) -> dict:
    return TEMPLATES[lang_or_default(lang)]


def sms_segments(text: str) -> int:
    if all(ch in GSM7 for ch in text):
        single, multi = 160, 153
    else:
        single, multi = 70, 67
    return 1 if len(text) <= single else math.ceil(len(text) / multi)


def localize_place(name: str, lang: str) -> str:
    if lang != "hi":
        return name
    out = name
    # Longest keys first so "lakhimpur kheri" wins over anything shorter.
    for en, hi in sorted(PLACE_NAMES_HI.items(), key=lambda kv: -len(kv[0])):
        idx = out.casefold().find(en)
        while idx != -1:
            out = out[:idx] + hi + out[idx + len(en):]
            idx = out.casefold().find(en, idx + len(hi))
    return out


def _short_source(src: str, limit: int = 24) -> str:
    src = (src or "Govt").strip()
    return src if len(src) <= limit else src[: limit - 1].rstrip() + "…"


def render_sms(facts: AlertFacts, lang: str, max_segments: int = 3) -> str:
    """Build the SMS, trimming the least important parts until it fits."""
    lang = lang_or_default(lang)
    T = TEMPLATES[lang]
    hazard = T["hazards"].get(facts.hazard, T["hazards"]["OTHER"])
    sev = T["severity"].get(facts.severity, "")
    tag = "" if facts.official else f" {T['forecast_tag']}"
    areas = [localize_place(a, lang) for a in facts.areas] or ["-"]
    actions = [T["actions"][a] for a in facts.actions if a in T["actions"]]
    # 112 is always a valid fallback in India, so there's never a message
    # with no number to call.
    phones = ", ".join(facts.helplines) if facts.helplines else "112"
    source = _short_source(facts.source_name)
    until = fmt_local(facts.valid_until)

    # Minor/unknown alerts say "advisory" so we don't cry wolf with "warning".
    word = T["warning"] if facts.severity in ("Extreme", "Severe", "Moderate") else T["advisory"]
    camp = facts.shelters[0] if facts.shelters else ""

    def build(area_list, action_list, with_source=True, with_camp=True):
        head = f"{T['brand']}: {sev}{hazard} {word}{tag} - {', '.join(area_list)}"
        parts = [head]
        if action_list:
            parts.append(action_list[0])
        # The camp name goes right after the first action ("evacuate") so
        # people know WHERE to go, not just that they should go.
        if camp and with_camp:
            parts.append(T["camp"].format(camp=camp))
        parts += action_list[1:]
        parts.append(T["call"].format(phones=phones))
        if until:
            parts.append(T["until"].format(time=until))
        if with_source:
            parts.append(T["source"].format(src=source))
        return T["sep"].join(parts)

    msg = build(areas, actions)
    # Trim order when too long, least important first:
    #   extra actions -> long area list -> source -> camp name.
    # The hazard, the first action and the helpline are never dropped.
    while sms_segments(msg) > max_segments and len(actions) > 1:
        actions.pop()
        msg = build(areas, actions)
    if sms_segments(msg) > max_segments and len(areas) > 1:
        areas = [areas[0], f"+{len(areas) - 1}"]
        msg = build(areas, actions)
    if sms_segments(msg) > max_segments:
        msg = build(areas, actions, with_source=False)
    if sms_segments(msg) > max_segments:
        msg = build(areas, actions, with_source=False, with_camp=False)
    return msg


def render_summary(facts: AlertFacts, lang: str) -> str:
    """
    The fuller version of an alert, for a STATUS reply where we aren't
    fighting for every character the way an outgoing push is.
    """
    lang = lang_or_default(lang)
    T = TEMPLATES[lang]
    actions = [T["actions"][a] for a in facts.actions if a in T["actions"]]
    phones = facts.helplines or ["112"]
    return T["summary"].format(
        sev=T["severity"].get(facts.severity, ""),
        hazard=T["hazards"].get(facts.hazard, T["hazards"]["OTHER"]),
        areas=", ".join(localize_place(a, lang) for a in facts.areas),
        actions=T["sep"].join(actions) if actions else "",
        phones=", ".join(phones[:2]),
        src=facts.source_name or "Govt",
    )