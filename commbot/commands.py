"""
Inbound SMS commands. Kept separate from Flask so the same logic works for
Twilio, an Android gateway, or a unit test.

Commands (case-insensitive):
  JOIN <district> [HI|EN]   subscribe / change district or language
  STATUS                    current alert for my district
  SHELTER                   relief camp info
  HELPLINE                  numbers to call
  STOP                      unsubscribe
  HELP                      list commands
"""
from __future__ import annotations

from .localize import SUPPORTED_LANGS, lang_or_default, render_sms, t
from .models import Subscriber
from .qa import answer_intent

JOIN_WORDS = {"JOIN", "SUBSCRIBE", "START", "जुड़ें"}
STOP_WORDS = {"STOP", "UNSUBSCRIBE", "बंद"}
STATUS_WORDS = {"STATUS", "ALERT", "INFO", "सूचना"}
SHELTER_WORDS = {"SHELTER", "CAMP", "शिविर", "आश्रय"}
HELPLINE_WORDS = {"HELPLINE", "NUMBER", "हेल्पलाइन"}


def handle_sms_command(store, phone: str, text: str, default_lang: str = "hi") -> str:
    sub = store.get_subscriber(phone)
    lang = lang_or_default(sub.lang if sub else default_lang)
    words = (text or "").split()
    if not words:
        return t(lang)["help"]

    cmd = words[0].upper()

    if cmd in JOIN_WORDS:
        rest = words[1:]
        # "JOIN Bahraich EN" -> the last word can be a language code.
        if rest and rest[-1].lower() in SUPPORTED_LANGS:
            lang = rest[-1].lower()
            rest = rest[:-1]
        if not rest:
            return t(lang)["need_district"]
        district = " ".join(rest).strip()
        store.upsert_subscriber(Subscriber(phone=phone, district=district, lang=lang))
        return t(lang)["joined"].format(district=district)

    if cmd in STOP_WORDS:
        store.deactivate_subscriber(phone)
        return t(lang)["stopped"]

    if sub is None or not sub.active:
        return t(lang)["unregistered"]

    alerts = store.active_alerts(sub.district)

    if cmd in STATUS_WORDS:
        if not alerts:
            return answer_intent("status", [], lang, sub.district)
        return render_sms(alerts[0], lang)
    if cmd in SHELTER_WORDS:
        return answer_intent("shelter", alerts, lang, sub.district)
    if cmd in HELPLINE_WORDS:
        return answer_intent("helpline", alerts, lang, sub.district)

    return t(lang)["help"]
