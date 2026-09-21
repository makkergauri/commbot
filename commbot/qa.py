"""
Answer citizen questions (from an inbound SMS) using ONLY stored official alerts.

This is keyword-based on purpose. A free-form chatbot answering "is the road
to Mahsi safe?" would be tempted to make something up. We answer the three
questions we can answer reliably (what's happening, where do I go, who do I
call) and send everything else to 112.
"""
from __future__ import annotations

from .localize import lang_or_default, render_summary, t

INTENT_KEYWORDS = {
    "shelter": ["shelter", "camp", "relief", "where should i go", "safe place",
                "आश्रय", "शिविर", "कैंप", "राहत", "कहाँ जाएं", "कहां जाएं", "कहाँ जाऊं"],
    "helpline": ["helpline", "number", "phone", "contact", "call",
                 "हेल्पलाइन", "नंबर", "फोन", "संपर्क"],
    "status": ["status", "alert", "warning", "water", "flood", "rain", "danger", "what is happening",
               "चेतावनी", "बाढ़", "पानी", "बारिश", "खतरा", "सूचना", "क्या हो रहा"],
}


def detect_intent(text: str) -> str:
    lowered = (text or "").casefold()
    for intent, words in INTENT_KEYWORDS.items():
        if any(w in lowered for w in words):
            return intent
    return "unknown"


def answer_intent(intent: str, alerts: list, lang: str, area_label: str = "") -> str:
    lang = lang_or_default(lang)
    T = t(lang)
    if not alerts:
        return T["no_alert"].format(area=area_label or "-")

    top = alerts[0]  # already sorted by score, most important first
    phones = ", ".join(top.helplines) if top.helplines else "112"

    if intent == "shelter":
        shelters = [s for a in alerts for s in a.shelters]
        if shelters:
            return T["shelter"].format(shelters="; ".join(dict.fromkeys(shelters)))
        return T["no_shelter"].format(phones=phones)
    if intent == "helpline":
        return T["helpline"].format(phones=phones)
    if intent == "status":
        return render_summary(top, lang)
    return T["unknown"]


def answer(question: str, alerts: list, lang: str, area_label: str = "") -> str:
    return answer_intent(detect_intent(question), alerts, lang, area_label)