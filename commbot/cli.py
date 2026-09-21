"""
Command-line entry point.

    python -m commbot.cli demo                 # try everything, no accounts needed
    python -m commbot.cli init-db
    python -m commbot.cli add-subscriber --phone +91XXXXXXXXXX --district Bahraich --lang hi
    python -m commbot.cli run-once             # one fetch/send cycle
    python -m commbot.cli run                  # loop forever
    python -m commbot.cli serve --port 5000    # SMS + voice webhooks
    python -m commbot.cli pending              # alerts waiting for a human
    python -m commbot.cli approve <alert_id> --by "Officer name"
    python -m commbot.cli reject <alert_id> --by "Officer name"
    python -m commbot.cli preview <alert_id>   # see the SMS + voice text in every language
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import timedelta

from .config import Settings
from .localize import SUPPORTED_LANGS, render_sms, render_summary, sms_segments
from .models import AlertFacts, Subscriber
from .storage import Store
from .utils import IST, now_utc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _deps(settings):
    from .channels import get_sender
    from .llm import get_llm

    return Store(settings.db_path), get_sender(settings), get_llm(settings)


def cmd_demo(args, settings) -> None:
    """
    End-to-end walkthrough with fake data and no external accounts.
    Sample alert dates are shifted to "now" so the demo works any day.
    """
    from .channels.sms import ConsoleSender
    from .commands import handle_sms_command
    from .ingest import parse_cap
    from .pipeline import dispatch, ingest

    db = os.path.join(HERE, "demo.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    store = Store(db)
    settings.require_approval = False  # skip the review queue for the demo

    print("\n=== 1. Registering three test subscribers ===")
    for phone, district, lang in [("+919000000001", "Bahraich", "hi"),
                                  ("+919000000002", "Bahraich", "en"),
                                  ("+919000000003", "Gorakhpur", "hi")]:
        store.upsert_subscriber(Subscriber(phone=phone, district=district, lang=lang))
        print(f"  {phone}  {district:10s} {lang}")

    print("\n=== 2. Ingesting sample CAP alerts ===")
    sent = (now_utc() - timedelta(minutes=5)).astimezone(IST).isoformat()
    expires = (now_utc() + timedelta(hours=12)).astimezone(IST).isoformat()
    raws = []
    for name in ("flood_alert.xml", "heat_advisory.xml", "exercise_alert.xml"):
        with open(os.path.join(HERE, "samples", name), encoding="utf-8") as fh:
            xml = fh.read()
        xml = re.sub(r"<sent>.*?</sent>", f"<sent>{sent}</sent>", xml)
        xml = re.sub(r"<expires>.*?</expires>", f"<expires>{expires}</expires>", xml)
        found = parse_cap(xml.encode("utf-8"), source="demo")
        print(f"  {name}: {'parsed' if found else 'skipped (not status=Actual)'}")
        raws.extend(found)

    from .llm import get_llm
    for facts, score_, status in ingest(raws, store, settings, get_llm(settings)):
        print(f"  -> {facts.alert_id}: {facts.hazard}/{facts.severity}, score {score_}, status '{status}'")
        print(f"     actions={facts.actions} helplines={facts.helplines} shelters={facts.shelters}")

    print("\n=== 3. Dispatching (only Bahraich subscribers should get the flood SMS) ===")
    n = dispatch(store, ConsoleSender(), settings)
    print(f"\n  {n} SMS sent.")

    print("\n=== 4. Running the pipeline again (duplicates must NOT be re-sent) ===")
    print(f"  {dispatch(store, ConsoleSender(), settings)} SMS sent.")

    print("\n=== 5. Citizens texting in ===")
    for phone, text in [("+919000000001", "SHELTER"),
                        ("+919000000002", "HELPLINE"),
                        ("+919000000003", "STATUS"),
                        ("+919000000099", "JOIN Lucknow EN"),
                        ("+919000000099", "STATUS")]:
        print(f"\n  {phone} > {text}")
        print(f"  CommBot < {handle_sms_command(store, phone, text)}")

    print("\n=== 6. What someone in Bahraich gets back if they text STATUS ===")
    top = store.active_alerts("Bahraich")[0]
    print("  " + render_summary(top, "hi"))
    print(f"\nDone. Demo database: {db}\n")


def cmd_init_db(args, settings) -> None:
    Store(settings.db_path)
    print(f"Database ready at {settings.db_path}")


def cmd_add_subscriber(args, settings) -> None:
    store = Store(settings.db_path)
    store.upsert_subscriber(Subscriber(phone=args.phone, district=args.district,
                                       lang=args.lang, lat=args.lat, lon=args.lon))
    print(f"Saved {args.phone} -> {args.district} ({args.lang})")


def cmd_run_once(args, settings) -> None:
    from .pipeline import run_once

    store, sender, llm = _deps(settings)
    print(json.dumps(run_once(settings, store, sender, llm), indent=2))


def cmd_run(args, settings) -> None:
    from .pipeline import run_forever

    store, sender, llm = _deps(settings)
    run_forever(settings, store, sender, llm)


def cmd_serve(args, settings) -> None:
    from .webhooks import create_app

    app = create_app(settings, Store(settings.db_path))
    # Flask's dev server is fine for testing. For production run it with
    # gunicorn:  gunicorn "commbot.wsgi:app" -b 0.0.0.0:5000 -w 2
    app.run(host="0.0.0.0", port=args.port)


def cmd_pending(args, settings) -> None:
    store = Store(settings.db_path)
    rows = store.list_alerts(["pending_review"])
    if not rows:
        print("Nothing waiting for review.")
    for row in rows:
        facts = AlertFacts.from_dict(json.loads(row["facts_json"]))
        print(f"\n{row['alert_id']}  score={row['score']}  created={row['created_at']}")
        print(f"  {facts.hazard}/{facts.severity}  areas={facts.areas}")
        print(f"  actions={facts.actions}  helplines={facts.helplines}  shelters={facts.shelters}")
        for w in facts.warnings:
            print(f"  ! {w}")
        print("  EN: " + render_sms(facts, "en"))


def _set(args, settings, status: str) -> None:
    store = Store(settings.db_path)
    if store.set_status(args.alert_id, status, reviewed_by=args.by):
        print(f"{args.alert_id} -> {status} (by {args.by}). It will go out on the next cycle."
              if status == "approved" else f"{args.alert_id} -> {status}")
    else:
        sys.exit(f"No alert with id {args.alert_id}")


def cmd_preview(args, settings) -> None:
    row = Store(settings.db_path).get_alert(args.alert_id)
    if not row:
        sys.exit(f"No alert with id {args.alert_id}")
    facts = AlertFacts.from_dict(json.loads(row["facts_json"]))
    for lang in SUPPORTED_LANGS:
        sms = render_sms(facts, lang, settings.max_sms_segments)
        print(f"\n[{lang}] SMS ({len(sms)} chars, {sms_segments(sms)} segments):\n{sms}")
        print(f"[{lang}] STATUS reply:\n{render_summary(facts, lang)}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="commbot", description="CommBot crisis alerts")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="run an offline end-to-end demo").set_defaults(fn=cmd_demo)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)

    p = sub.add_parser("add-subscriber")
    p.add_argument("--phone", required=True, help="E.164 format, e.g. +919876543210")
    p.add_argument("--district", required=True)
    p.add_argument("--lang", default="hi", choices=SUPPORTED_LANGS)
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.set_defaults(fn=cmd_add_subscriber)

    sub.add_parser("run-once").set_defaults(fn=cmd_run_once)
    sub.add_parser("run").set_defaults(fn=cmd_run)

    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=5000)
    p.set_defaults(fn=cmd_serve)

    sub.add_parser("pending").set_defaults(fn=cmd_pending)
    for name, status in (("approve", "approved"), ("reject", "rejected")):
        p = sub.add_parser(name)
        p.add_argument("alert_id")
        p.add_argument("--by", required=True, help="who reviewed it (kept for the audit trail)")
        p.set_defaults(fn=lambda a, s, st=status: _set(a, s, st))

    p = sub.add_parser("preview")
    p.add_argument("alert_id")
    p.set_defaults(fn=cmd_preview)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    args.fn(args, Settings())


if __name__ == "__main__":
    main()
