"""
The control room, as five small pages rather than one long scroll.

  Overview     what needs deciding, plus a map of what's happening
  Alerts       everything current, filterable by hazard
  Coverage     who receives messages and in which language
  Activity     proof of what was actually delivered
  How it works the explanation, for anyone opening the link cold

I split it up because a duty officer only ever needs the first page, and every
other question then has somewhere to live without cluttering it.
"""
from __future__ import annotations

import json
import re

from flask import Blueprint, Response, redirect, request

from .extract import HAZARDS
from .localize import render_sms, sms_segments
from .models import AlertFacts
from .ui import (bar, donut, esc, hazard_colour, hazard_icon, hazard_name, icon,
                 layout, map_svg, phone, sample_tag, severity_colour, tile)
from .utils import fmt_local, now_utc, parse_iso

# Enough to place a dot on the map. Alerts rarely carry coordinates, but the
# issuing authority almost always names its state ("Kerala-SDMA") or its city
# ("IMD-Ranchi"), which is accurate enough for an overview at this zoom.
PLACES = {
    "andhra pradesh": (15.9, 79.7), "arunachal": (28.2, 94.7), "assam": (26.2, 92.9),
    "bihar": (25.8, 85.3), "chhattisgarh": (21.3, 81.9), "goa": (15.3, 74.1),
    "gujarat": (22.6, 71.7), "haryana": (29.2, 76.4), "himachal": (31.9, 77.2),
    "jharkhand": (23.6, 85.3), "karnataka": (14.8, 76.0), "kerala": (10.5, 76.3),
    "madhya pradesh": (23.5, 78.5), "maharashtra": (19.4, 75.8), "manipur": (24.7, 93.9),
    "meghalaya": (25.5, 91.4), "mizoram": (23.3, 92.9), "nagaland": (26.2, 94.5),
    "odisha": (20.4, 84.5), "punjab": (31.0, 75.4), "rajasthan": (26.8, 73.8),
    "sikkim": (27.5, 88.5), "tamil nadu": (11.1, 78.5), "telangana": (17.9, 79.0),
    "tripura": (23.7, 91.6), "uttar pradesh": (26.9, 80.9), "uttarakhand": (30.1, 79.1),
    "west bengal": (23.5, 87.8), "delhi": (28.6, 77.2), "puducherry": (11.9, 79.8),
    "pondicherry": (11.9, 79.8), "jammu": (33.3, 75.3), "kashmir": (34.1, 74.8),
    "ladakh": (34.2, 77.6), "andaman": (11.7, 92.7), "daman": (20.4, 72.8),
    "dadra": (20.3, 73.0), "diu": (20.7, 70.9), "chandigarh": (30.7, 76.8),
    # Met office cities, since IMD names the office rather than the state.
    "mumbai": (19.1, 72.9), "kolkata": (22.6, 88.4), "chennai": (13.1, 80.3),
    "bengaluru": (13.0, 77.6), "hyderabad": (17.4, 78.5), "ahmedabad": (23.0, 72.6),
    "lucknow": (26.8, 81.0), "patna": (25.6, 85.1), "ranchi": (23.4, 85.3),
    "bhopal": (23.3, 77.4), "jaipur": (26.9, 75.8), "nagpur": (21.1, 79.1),
    "guwahati": (26.1, 91.7), "thiruvananthapuram": (8.5, 77.0), "bhubaneswar": (20.3, 85.8),
    "shimla": (31.1, 77.2), "dehradun": (30.3, 78.0), "srinagar": (34.1, 74.8),
}


def mask(phone: str) -> str:
    """+919876543210 -> +91*****210. Enough to tell rows apart, not to call anyone."""
    return f"{phone[:3]}*****{phone[-3:]}" if len(phone) > 6 else "***"


def _facts(row) -> AlertFacts:
    return AlertFacts.from_dict(json.loads(row["facts_json"]))


def ago(iso: str) -> str:
    """'2 min ago', or an honest 'not yet' when no cycle has finished."""
    when = parse_iso(iso)
    if not when:
        return "not yet"
    minutes = int((now_utc() - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60}h ago"


def time_left(valid_until: str) -> str:
    """"3h left" reads better than a timestamp when you're in a hurry."""
    end = parse_iso(valid_until)
    if not end:
        return ""
    minutes = int((end - now_utc()).total_seconds() // 60)
    if minutes <= 0:
        return "expired"
    if minutes < 60:
        return f"{minutes} min left"
    if minutes < 48 * 60:
        return f"{minutes // 60}h left"
    return f"{minutes // 1440} days left"


def locate(facts: AlertFacts):
    """Best guess at where an alert belongs on the map."""
    if facts.polygons:
        points = facts.polygons[0]
        return (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))
    # Sender names arrive hyphenated ("West-Bengal-SDMA"), so flatten
    # everything to plain words before looking for a place name.
    haystack = re.sub(r"[^a-z]+", " ",
                      " ".join([facts.source_name or "", *facts.areas]).casefold())
    # Longest names first, so "andhra pradesh" beats a stray "andhra".
    for name, coords in sorted(PLACES.items(), key=lambda kv: -len(kv[0])):
        if name in haystack:
            return coords
    return None


def alert_card(row, token: str, read_only: bool = False) -> str:
    facts = _facts(row)
    sev = severity_colour(facts.severity)
    haz = hazard_colour(facts.hazard)
    flags = "".join(f'<div class="flag">{esc(w)}</div>' for w in facts.warnings)
    hi, en = render_sms(facts, "hi"), render_sms(facts, "en")
    form = f"""<form method="post" action="/dashboard/review" class="acts">
        <input type="hidden" name="alert_id" value="{esc(row['alert_id'])}">
        <input type="hidden" name="token" value="{esc(token)}">
        <button class="go" name="action" value="approve">Approve and send</button>
        <button class="no" name="action" value="reject">Reject</button>
      </form>"""
    # In the public demo a visitor sees what an officer would decide on,
    # without being able to decide it for them.
    demo_note = ('<div class="flag" style="color:#a5f3fc;background:rgba(34,211,238,.08);'
                 'border-color:rgba(34,211,238,.25)">In a live deployment a duty officer '
                 'approves or rejects this here. If nobody does within 10 minutes, official '
                 'alerts are released automatically.</div>')
    # The action has to be the full path. I used a relative "review" first and
    # it posted to /review, which lands outside this blueprint.
    return f"""<div class="card alert">
      <div style="position:absolute;left:0;top:0;bottom:0;width:3px;background:{sev}"></div>
      <div class="head">
        <div class="hicon" style="background:{haz}1f">{icon(hazard_icon(facts.hazard), haz, 20)}</div>
        <div class="title">{esc(hazard_name(facts.hazard))}</div>
        <span class="badge" style="background:{sev}">{esc(facts.severity)}</span>
      </div>
      <div class="where">{esc(', '.join(facts.areas) or 'Area not named')}</div>
      <div class="meta">{esc(facts.headline[:200])}</div>
      <div class="meta">Issued by {esc(facts.source_name or 'unknown')} &middot;
        valid till {esc(fmt_local(facts.valid_until))} ({esc(time_left(facts.valid_until))})</div>
      <div class="phones">
        {phone('Hindi', hi, sms_segments(hi))}
        {phone('English', en, sms_segments(en))}
      </div>
      {flags}
      {demo_note if read_only else form}</div>"""


def alert_row(row) -> str:
    facts = _facts(row)
    sev = severity_colour(facts.severity)
    return f"""<div class="item"><span class="dot" style="background:{sev}"></span>
      <div><div class="nm">{esc(hazard_name(facts.hazard))} &middot; {esc(facts.severity)}</div>
      <div class="ar">{esc(', '.join(facts.areas) or 'Area not named')}</div></div>
      <div class="rt"><b>{esc(time_left(facts.valid_until))}</b>{esc(fmt_local(facts.valid_until))}</div>
      </div>"""


def strip_items(rows, limit: int = 10):
    """Short lines for the scrolling strip under the nav."""
    items = []
    for row in rows[:limit]:
        facts = _facts(row)
        items.append((severity_colour(facts.severity),
                      hazard_name(facts.hazard),
                      f"{', '.join(facts.areas) or 'area not named'} - "
                      f"{time_left(facts.valid_until)}"))
    return items


def readout(big, caption, rows) -> str:
    """The glowing number beside the headline."""
    lines = "".join(f'<div class="row"><span>{esc(k)}</span><b>{esc(v)}</b></div>'
                    for k, v in rows)
    return f"""<div class="readout"><div class="big">{esc(big)}</div>
      <div class="cap">{esc(caption)}</div>{lines}</div>"""


def alert_list(rows, empty_text: str) -> str:
    if not rows:
        return f'<div class="empty">{esc(empty_text)}</div>'
    return f'<div class="card list">{"".join(alert_row(r) for r in rows)}</div>'


def create_blueprint(settings, store) -> Blueprint:
    bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

    def authorised() -> bool:
        # One shared token is enough: the pages show alerts, not personal data,
        # and the people using them share a duty phone anyway.
        if not settings.dashboard_token:
            return True
        return request.values.get("token", "") == settings.dashboard_token

    def guard():
        if not authorised():
            return Response("Add ?token=... to the address to open this page.", status=403)
        return None

    def counts():
        return (store.list_alerts(["pending_review"], limit=40),
                store.list_alerts(["approved", "dispatched"], limit=80),
                store.list_alerts(["info_only"], limit=80))

    # ---------------------------------------------------------------- overview

    @bp.get("")
    def overview():
        blocked = guard()
        if blocked:
            return blocked
        token = request.values.get("token", "")
        pending, live, logged = counts()
        subs = store.list_active_subscribers()
        totals = store.delivery_totals()
        last = store.get_meta("last_cycle")
        # No finished cycle and nothing stored means this copy has only just
        # woken up, which is very different from "nothing is happening".
        starting = not last and store.count_alerts() == 0
        tracked = len(pending) + len(live) + len(logged)

        tiles = "".join([
            tile(len(pending), "Waiting for approval",
                 "A person checks these before anything is sent.", "#ffc53d", "clock"),
            tile(len(live), "Live warnings", "Active now and cleared to send.", "#ff2d55", "bolt"),
            tile(len(subs), "People signed up" + (sample_tag() if settings.demo_mode else ""),
                 "Each gets only their own district.", "#a78bfa", "people"),
            tile(totals.get("sent", 0),
                 "Messages delivered" + (sample_tag() if settings.demo_mode else ""),
                 f"{totals.get('failed', 0)} failed to send.", "#34d399", "send"),
        ])

        located = []
        for row in pending + live:
            facts = _facts(row)
            spot = locate(facts)
            if spot:
                located.append((spot[0], spot[1], severity_colour(facts.severity),
                                f"{hazard_name(facts.hazard)} - "
                                f"{', '.join(facts.areas) or 'area not named'}"))
        legend = "".join(f'<span><i style="width:10px;height:10px;border-radius:50%;'
                         f'background:{severity_colour(s)};display:inline-block"></i>{s}</span>'
                         for s in ("Extreme", "Severe", "Moderate", "Minor"))

        live_facts = [_facts(r) for r in live]
        bars = "".join(
            bar(hazard_name(h), sum(1 for f in live_facts if f.hazard == h),
                len(live_facts) or 1, hazard_colour(h))
            for h in HAZARDS if any(f.hazard == h for f in live_facts))

        body = f"""
        <section><div class="grid g4">{tiles}</div></section>

        <section><h2>Needs your decision</h2>
          {"".join(alert_card(r, token, settings.demo_mode) for r in pending[:4])
           or f'<div class="empty">{"Reading the feed now, nothing to show yet." if starting else "Nothing is waiting. New warnings appear here for approval."}</div>'}
          {f'<a class="chip" href="/dashboard/alerts{"?token=" + token if token else ""}">'
             f'See all {len(pending)} waiting</a>' if len(pending) > 4 else ''}
        </section>

        <section class="grid g2">
          <div class="card pad"><h3>Where the warnings are</h3>
            <p class="note">Every alert in play, live or awaiting approval, placed by the
               authority that issued it.</p>
            {map_svg(located)}<div class="legend">{legend}</div></div>
          <div class="card pad"><h3>What kind of warnings</h3>
            <p class="note">Live warnings by hazard type.</p>
            {bars or '<p class="note">Nothing live right now.</p>'}
            <div class="kv"><span>Logged but not sent</span><b>{len(logged)}</b></div>
            <div class="kv"><span>Districts covered</span>
              <b>{len({s.district for s in subs})}</b></div>
          </div>
        </section>"""

        if starting:
            # A visitor landing during a cold start shouldn't be told all is
            # well. Nothing has been checked yet, and that's a different thing.
            headline = "Fetching the latest warnings"
            lede = ("This copy just woke up and is reading India's national alert feed. "
                    "Give it a moment, then refresh.")
        elif settings.demo_mode:
            headline = ("Live disaster warnings across India" if tracked
                        else "No warnings are active right now")
            lede = ("Official warnings, turned into short messages in people's own language "
                    "and sent by SMS to the districts affected. This page shows the real feed, "
                    "as a duty officer would see it.")
        else:
            headline = ("Warnings are waiting for your decision" if pending
                        else "All clear across the network")
            lede = ("Official disaster warnings, turned into short messages in people's own "
                    "language and sent by SMS to the districts affected.")

        # On the hosted copy nobody can approve anything, so the headline
        # number is everything being tracked rather than what's cleared to send.
        big = tracked if settings.demo_mode else len(live)
        caption = ("warnings being tracked right now" if settings.demo_mode
                   else "live warnings being tracked right now")
        aside = readout(big, caption, [
            ("Live now", len(live)),
            ("Awaiting approval", len(pending)),
            ("People covered", len(subs)),
            ("Feed last checked", ago(last)),
        ])
        return Response(layout("", "Live from India's alert feeds", headline, lede,
                               body, token, aside, strip_items(pending + live), settings.demo_mode),
                        mimetype="text/html")

    # ------------------------------------------------------------------ alerts

    @bp.get("/alerts")
    def alerts():
        blocked = guard()
        if blocked:
            return blocked
        token = request.values.get("token", "")
        chosen = request.args.get("hazard", "")
        pending, live, logged = counts()
        live_facts = [_facts(r) for r in live]

        def link(hazard: str) -> str:
            bits = [b for b in (f"token={token}" if token else "",
                                f"hazard={hazard}" if hazard else "") if b]
            return "/dashboard/alerts" + ("?" + "&".join(bits) if bits else "")

        chips = [f'<a class="chip{"" if chosen else " on"}" href="{link("")}">All {len(live)}</a>']
        for hazard in HAZARDS:
            count = sum(1 for f in live_facts if f.hazard == hazard)
            if count:
                chips.append(f'<a class="chip{" on" if chosen == hazard else ""}" '
                             f'href="{link(hazard)}">{esc(hazard_name(hazard))} {count}</a>')
        shown = [r for r in live if not chosen or _facts(r).hazard == chosen]

        body = f"""
        <section><h2>Waiting for approval ({len(pending)})</h2>
          {"".join(alert_card(r, token, settings.demo_mode) for r in pending)
           or '<div class="empty">Nothing is waiting.</div>'}</section>
        <section><h2>Live warnings</h2><div class="chips">{"".join(chips)}</div>
          {alert_list(shown, "No warnings are live right now.")}</section>
        <section><h2>Logged, not sent</h2>
          <p class="note">Minor or unclear alerts, and alerts with no area I can match to a district.
             People can still ask for these by texting STATUS.</p>
          {alert_list(logged[:12], "Nothing logged.")}</section>"""

        aside = readout(len(live) + len(pending) + len(logged), "alerts held right now", [
            ("Live", len(live)), ("Awaiting approval", len(pending)),
            ("Logged only", len(logged)),
        ])
        return Response(layout("/alerts", "Everything currently known",
                               "Every warning in play, and what happens to it",
                               "Alerts are scored on severity, urgency and certainty. Only the "
                               "serious ones are pushed as SMS; the rest stay available on request.",
                               body, token, aside, strip_items(pending + live), settings.demo_mode),
                        mimetype="text/html")

    # ---------------------------------------------------------------- coverage

    @bp.get("/people")
    def people():
        blocked = guard()
        if blocked:
            return blocked
        token = request.values.get("token", "")
        subs = store.list_active_subscribers()
        districts = {}
        for sub in subs:
            districts[sub.district] = districts.get(sub.district, 0) + 1
        top = sorted(districts.items(), key=lambda kv: -kv[1])[:10]
        hindi = sum(1 for s in subs if s.lang == "hi")
        bars = "".join(bar(d, n, max(districts.values()) if districts else 1, "#22d3ee")
                       for d, n in top)
        rows = "".join(
            f"<tr><td>{esc(s.phone[:3])}&bull;&bull;&bull;&bull;&bull;{esc(s.phone[-3:])}</td>"
            f"<td>{esc(s.district)}</td><td>{'Hindi' if s.lang == 'hi' else 'English'}</td></tr>"
            for s in subs[:25])

        body = f"""
        <section class="grid g2">
          <div class="card pad"><h3>Districts covered</h3>
            <p class="note">People are matched to an alert by their district name, or by GPS
               when the alert carries a boundary.</p>
            {bars or '<p class="note">No one has signed up yet.</p>'}</div>
          <div class="card pad"><h3>Language</h3>
            <p class="note">Every message is built from phrases reviewed by a speaker of that
               language, never machine-translated on the spot.</p>
            {donut([("Hindi", hindi, "#a78bfa"), ("English", len(subs) - hindi, "#22d3ee")])}</div>
        </section>
        <section><h2>Subscribers</h2><div class="card pad">
          <p class="note">{"These are sample entries on the hosted copy, not real people. " if settings.demo_mode else ""}Numbers are part-hidden here. People join by texting JOIN and their
             district, and leave by texting STOP.</p>
          {f'<table><tr><th>Number</th><th>District</th><th>Language</th></tr>{rows}</table>'
           if rows else '<p class="note">Nobody has signed up yet.</p>'}</div></section>"""

        aside = readout(len(subs), "people signed up to receive warnings", [
            ("Districts covered", len(districts)),
            ("Hindi", hindi), ("English", len(subs) - hindi),
            ("Cost per person", "one SMS"),
        ])
        return Response(layout("/people",
                               "Sample subscribers" if settings.demo_mode else "Who receives the alerts",
                               "Reaching people on the phones they already own",
                               "Nobody is added without asking. Joining, changing language and "
                               "leaving all happen by SMS, so a basic phone is enough.",
                               body, token, aside, None, settings.demo_mode), mimetype="text/html")

    # ---------------------------------------------------------------- activity

    @bp.get("/activity")
    def activity():
        blocked = guard()
        if blocked:
            return blocked
        token = request.values.get("token", "")
        totals = store.delivery_totals()
        sent, failed = totals.get("sent", 0), totals.get("failed", 0)
        rows = "".join(
            f"<tr><td>{esc(mask(d['phone']))}</td>"
            f"<td><span class='pill {esc(d['status'])}'>{esc(d['status'])}</span></td>"
            f"<td style='color:#5b6478'>{esc(d['alert_id'].split(':')[-1][:26])}</td>"
            f"<td style='text-align:right;color:#5b6478'>{esc(fmt_local(d['sent_at']))}</td></tr>"
            for d in store.recent_deliveries(25))

        body = f"""
        <section><div class="grid g4">
          {tile(sent, "Delivered", "Messages that reached a phone.", "#34d399", "check")}
          {tile(failed, "Failed", "Retried three times before giving up.", "#ff2d55", "clock")}
          {tile(f"{round(100 * sent / (sent + failed)) if sent + failed else 100}%",
                "Success rate", "Across every message ever sent.", "#22d3ee", "send")}
        </div></section>
        <section><h2>Message log</h2><div class="card pad">
          <p class="note">Every send is recorded: who it went to, for which alert, and whether
             it worked. This is the audit trail a district authority would ask for.</p>
          {f'<table><tr><th>To</th><th>Status</th><th>Alert</th>'
           f'<th style="text-align:right">Sent</th></tr>{rows}</table>'
           if rows else '<p class="note">No messages sent yet.</p>'}</div></section>"""

        aside = readout(sent, "messages delivered so far", [
            ("Failed", failed),
            ("Retries per message", 3),
            ("Duplicate messages", 0),
            ("Hourly cap per person", 4),
        ])
        return Response(layout("/activity",
                               "Sample delivery log" if settings.demo_mode else "What actually went out",
                               "Every message, logged and accounted for",
                               "Nobody gets the same warning twice, and nobody gets more than a "
                               "few messages an hour unless the situation is extreme.",
                               body, token, aside, None, settings.demo_mode), mimetype="text/html")

    # --------------------------------------------------------------- explainer

    @bp.get("/about")
    def about():
        blocked = guard()
        if blocked:
            return blocked
        token = request.values.get("token", "")
        steps = [
            ("Read the official feed",
             "CommBot polls NDMA's SACHET platform every two minutes. Those alerts come from "
             "IMD, the Central Water Commission and state authorities in a machine-readable "
             "format, so severity, urgency and area arrive as data rather than prose."),
            ("Pull out only the facts",
             "Hazard type, affected districts, recommended actions, helpline numbers and relief "
             "camps. Anything that can't be found word-for-word in the official text is thrown "
             "away, including anything a language model suggests."),
            ("Decide who needs it",
             "Each alert is scored on severity, urgency and certainty. Serious ones go to a "
             "person for approval; the rest stay available on request. People are matched by "
             "district, or by GPS when the alert carries a boundary."),
            ("Write it in their language",
             "Messages are assembled from phrases checked by native speakers, never "
             "machine-translated live. A Hindi SMS only holds 70 characters, so the hazard, the "
             "first action and a helpline are kept and everything else is trimmed."),
            ("Send it, once",
             "SMS goes out through a phone gateway, so it needs cell signal but no internet. "
             "The delivery log stops anyone receiving the same warning twice."),
        ]
        # Built in a plain loop: an f-string can't hold a backslash-escaped
        # quote on Python 3.11, and this reads better anyway.
        blocks = []
        for i, (title, detail) in enumerate(steps):
            line = '<div class="line"></div>' if i < len(steps) - 1 else ""
            blocks.append(f'<div class="step"><div class="col">'
                          f'<div class="num">{i + 1}</div>{line}</div>'
                          f'<div class="txt"><h3>{esc(title)}</h3>'
                          f'<p class="note" style="margin:0;max-width:70ch">{esc(detail)}</p>'
                          f'</div></div>')
        cards = "".join(blocks)

        rules = [
            "A language model may pick from fixed lists and copy text that exists in the alert. "
            "It never writes the warning itself.",
            "Official severity always wins over anything inferred.",
            "No evacuation instruction unless the source actually says to evacuate.",
            "Drills and test alerts never reach a phone.",
            "Every message names its source and always carries a working number to call.",
            "If a feed, model or network fails, alerts still go out using the simpler path.",
        ]
        rule_list = "".join(f'<div class="kv"><span>{esc(r)}</span></div>' for r in rules)

        body = f"""
        <section><h2>How a warning travels</h2>{cards}</section>
        <section><h2>Rules the system follows</h2>
          <div class="card pad"><p class="note">These exist because a wrong instruction during a
             flood is worse than no instruction at all.</p>{rule_list}</div></section>"""

        aside = readout("2 min", "from a government bulletin to a ringing phone", [
            ("Languages", "Hindi, English"),
            ("Works without internet", "yes, cell signal only"),
            ("Invented facts allowed", "none"),
        ])
        return Response(layout("/about", "The short explanation",
                               "From a government feed to a phone in about two minutes",
                               "CommBot doesn't decide that a flood is coming. It takes warnings "
                               "that already exist and makes sure they reach people who can read "
                               "them, on phones that can receive them.",
                               body, token, aside, None, settings.demo_mode), mimetype="text/html")

    # ------------------------------------------------------------------ action

    @bp.post("/review")
    def review():
        if not authorised() or settings.demo_mode:
            return Response("Not allowed.", status=403)
        alert_id = request.form.get("alert_id", "")
        status = "approved" if request.form.get("action") == "approve" else "rejected"
        # Whoever holds the duty phone is the reviewer. For real names in the
        # audit trail, put logins in front of these pages.
        store.set_status(alert_id, status, reviewed_by="dashboard")
        token = request.form.get("token", "")
        return redirect(f"/dashboard?token={token}" if token else "/dashboard")

    return bp