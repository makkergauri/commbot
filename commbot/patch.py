"""
One-off patcher for the pending edits.

Safe to run more than once: each change is applied only if it's missing.
Delete this file once everything reports OK.
"""
from pathlib import Path

changes = []


def rewrite(path: str, text: str):
    p = Path(path)
    if p.exists() and p.read_text(encoding="utf-8").strip() == text.strip():
        changes.append(f"already correct: {path}")
        return
    p.write_text(text, encoding="utf-8")
    changes.append(f"REWROTE: {path}")


def swap(path: str, old: str, new: str, label: str):
    p = Path(path)
    body = p.read_text(encoding="utf-8")
    if new in body:
        changes.append(f"already correct: {label}")
        return
    if old not in body:
        changes.append(f"COULD NOT FIND, fix by hand: {label}")
        return
    p.write_text(body.replace(old, new, 1), encoding="utf-8")
    changes.append(f"PATCHED: {label}")


# 1. The ingest package must export the polygon helpers.
rewrite("commbot/ingest/__init__.py",
        "from .cap_feed import add_polygons, fetch_feed, fetch_polygon, parse_cap  # noqa: F401\n"
        "from .weather import fetch_rain_alerts  # noqa: F401\n")

# 2. The approve button has to post inside the dashboard blueprint.
swap("commbot/dashboard.py",
     '<form method="post" action="review">',
     '<form method="post" action="/dashboard/review">',
     "dashboard approve button")

# 3. Aviation shorthand is not a place name.
swap("commbot/extract.py",
     '               "mod tsra", "tsra"}  # TSRA is aviation code for thunderstorm+rain, not a place',
     '               # Aviation shorthand that some state feeds put in areaDesc.\n'
     '               # TSRA/MTS mean thunderstorm with rain, they are not places.\n'
     '               "mod tsra", "tsra", "mts", "mod rain with mts", "rain with mts"}',
     "aviation codes in VAGUE_AREAS")

# 4. Alerts nobody can be matched to should not sit in the review queue.
swap("commbot/pipeline.py",
     'def decide_status(facts, alert_score: float, settings) -> str:\n'
     '    if alert_score < settings.push_threshold:',
     'def decide_status(facts, alert_score: float, settings) -> str:\n'
     '    if not facts.areas and not facts.polygons:\n'
     '        # Nobody can be matched to this one, so queuing it for review only\n'
     '        # wastes the reviewer\'s time. Keep it readable on request instead.\n'
     '        return "info_only"\n'
     '    if alert_score < settings.push_threshold:',
     "decide_status untargetable check")

print("\n".join(changes))