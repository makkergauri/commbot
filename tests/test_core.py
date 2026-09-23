"""
Tests for the parts that matter most for safety:
  - LLM output that isn't in the source gets thrown away
  - drills/exercises never go out
  - people don't get the same alert twice
  - messages fit in the SMS budget
Run with:  pytest -q
"""
import os
import re
from datetime import timedelta

import pytest

from commbot.config import Settings
from commbot.extract import extract_facts, extract_phone_numbers
from commbot.ingest import parse_cap
from commbot.localize import render_sms, sms_segments
from commbot.models import RawAlert, Subscriber
from commbot.pipeline import dispatch, ingest
from commbot.prioritize import score, subscriber_matches
from commbot.qa import detect_intent
from commbot.storage import Store
from commbot.utils import IST, now_utc

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "samples")


def load_sample(name: str) -> bytes:
    """Load a sample and shift its dates to 'now' so tests never expire."""
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as fh:
        xml = fh.read()
    sent = (now_utc() - timedelta(minutes=5)).astimezone(IST).isoformat()
    exp = (now_utc() + timedelta(hours=6)).astimezone(IST).isoformat()
    # (?:\w+:)? also matches prefixed tags like <cap:sent> in real SACHET files.
    for tag, value in (("sent", sent), ("expires", exp)):
        xml = re.sub(rf"<((?:\w+:)?){tag}>.*?</\1{tag}>",
                     lambda m, t=tag, v=value: f"<{m.group(1)}{t}>{v}</{m.group(1)}{t}>", xml)
    return xml.encode("utf-8")


class FakeLLM:
    """Pretends to be an LLM that hallucinates a bit."""

    def __init__(self, reply: str):
        self.reply = reply

    def complete(self, system, user, max_tokens=600):
        return self.reply


@pytest.fixture
def settings():
    s = Settings()
    s.require_approval = False
    s.push_threshold = 6
    s.max_sms_per_hour = 4
    s.resend_cooldown_min = 180
    s.firebase_cred = ""
    s.webhook_token = ""
    s.dashboard_token = ""
    return s


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


# ---------------- parsing ----------------

def test_parse_cap_prefers_english_block():
    alert = parse_cap(load_sample("flood_alert.xml"), source="t")[0]
    assert alert.event == "Flood"
    assert alert.severity == "Severe"
    assert "Bahraich" in alert.areas[0]
    assert len(alert.polygons[0]) == 5


def test_exercise_alerts_are_ignored():
    assert parse_cap(load_sample("exercise_alert.xml")) == []


# ---------------- extraction ----------------

def test_phone_extraction_ignores_dates_and_rainfall():
    text = "On 20/09/2026, 115 mm rain. Call 1077, 05252-000000 or +91 98765 43210."
    assert extract_phone_numbers(text) == ["1077", "05252000000", "9876543210"]


def test_llm_hallucinations_are_dropped():
    raw = parse_cap(load_sample("flood_alert.xml"), source="t")[0]
    # LLMs often wrap JSON in a markdown fence (three backticks), so we fake that too.
    fence = "`" * 3
    llm = FakeLLM(fence + "json\n"
                  '{"hazard": "FLOOD", "severity": "Extreme",'
                  ' "areas": ["Mahsi", "Nanpara"],'
                  ' "actions": ["MOVE_HIGHER", "MAKE_TEA"],'
                  ' "helplines": ["1077", "9999999999"],'
                  ' "shelters": ["Government Inter College, Mahsi", "District Stadium"]}'
                  "\n" + fence)
    facts = extract_facts(raw, llm)

    assert facts.severity == "Severe"            # CAP value beats the LLM
    assert "9999999999" not in facts.helplines   # invented number removed
    assert "District Stadium" not in facts.shelters
    assert "Nanpara" not in facts.areas
    assert "MAKE_TEA" not in facts.actions
    assert any("9999999999" in w for w in facts.warnings)


def test_evacuate_requires_evidence_in_source():
    raw = RawAlert(source="t", source_id="1", event="Heavy Rain",
                   body="Heavy rain likely in Sitapur.", areas=["Sitapur"])
    llm = FakeLLM('{"hazard": "HEAVY_RAIN", "actions": ["EVACUATE", "AVOID_TRAVEL"]}')
    facts = extract_facts(raw, llm)
    assert "EVACUATE" not in facts.actions


def test_broken_llm_falls_back_to_rules():
    raw = parse_cap(load_sample("flood_alert.xml"), source="t")[0]
    facts = extract_facts(raw, FakeLLM("sorry, I can't help with that"))
    assert facts.hazard == "FLOOD"
    assert facts.extraction_method == "rules"
    assert "1077" in facts.helplines


def test_areas_from_text():
    from commbot.extract import areas_from_text

    assert areas_from_text("Heavy rain likely in Lucknow, Barabanki and Sitapur districts today.") == \
        ["Lucknow", "Barabanki", "Sitapur"]
    assert areas_from_text("Heavy rain likely at some places.") == []


def test_count_only_areas_are_treated_as_vague():
    from commbot.extract import is_vague_area

    assert is_vague_area("9 districts of Gujarat")
    assert is_vague_area("6 Mandals")
    assert is_vague_area("MOD TSRA")
    assert is_vague_area("Mod Rain with MTS")
    assert not is_vague_area("Gumla, Lohardaga, Ranchi districts of Jharkhand")
    assert not is_vague_area("Bahraich")


def test_area_names_are_tidied():
    """Real SACHET areaDesc values, cleaned down to just the place names."""
    from commbot.extract import tidy_area

    assert tidy_area("Idukki,Kottayam districts of Kerala") == "Idukki, Kottayam"
    assert tidy_area("Jhargram district of West Bengal") == "Jhargram"
    assert tidy_area("mkp-kanigiri, mkp-veligandla mandals") == "mkp-kanigiri, mkp-veligandla"
    assert tidy_area("Bagmati, Benibad, Muzaffarpur, Bihar") == "Bagmati, Benibad, Muzaffarpur, Bihar"
    assert tidy_area("Bahraich") == "Bahraich"


def test_sdma_guidelines_count_as_advice():
    raw = RawAlert(source="t", source_id="1", event="Thunderstorm with Lightning",
                   title="Lightning likely over Ranchi.",
                   instruction="Please follow SDMA guidelines.",
                   areas=["Ranchi district of Jharkhand"])
    facts = extract_facts(raw)
    assert facts.actions == ["FOLLOW_OFFICIALS"]
    assert facts.areas == ["Ranchi"]
    assert "प्रशासन" in render_sms(facts, "hi")


# ---------------- decisions ----------------

def test_scores():
    raw = parse_cap(load_sample("flood_alert.xml"), source="t")[0]
    assert score(extract_facts(raw)) == pytest.approx(7.2)
    heat = parse_cap(load_sample("heat_advisory.xml"), source="t")[0]
    assert score(extract_facts(heat)) < 6


def test_targeting_by_name_and_polygon():
    facts = extract_facts(parse_cap(load_sample("flood_alert.xml"), source="t")[0])
    assert subscriber_matches(Subscriber("+91", "Bahraich"), facts)
    assert not subscriber_matches(Subscriber("+91", "Gorakhpur"), facts)
    # Unknown district name but GPS point inside the polygon
    assert subscriber_matches(Subscriber("+91", "somewhere", lat=27.7, lon=81.6), facts)


def test_untargetable_alerts_skip_the_review_queue(store, settings):
    """An alert with no area and no polygon can't reach anyone."""
    from commbot.pipeline import decide_status

    settings.require_approval = True
    raw = RawAlert(source="t", source_id="1", event="Thunderstorm",
                   title="Light rain over the state.", areas=["24 districts of Gujarat"],
                   severity="Severe", urgency="Immediate", certainty="Observed")
    facts = extract_facts(raw)
    assert facts.areas == []
    assert decide_status(facts, 12.0, settings) == "info_only"


def test_no_duplicate_sms(store, settings):
    from commbot.channels.sms import ConsoleSender

    store.upsert_subscriber(Subscriber("+919000000001", "Bahraich", "hi"))
    store.upsert_subscriber(Subscriber("+919000000002", "Gorakhpur", "hi"))
    raws = parse_cap(load_sample("flood_alert.xml"), source="t")

    sender = ConsoleSender(quiet=True)
    ingest(raws, store, settings)
    assert dispatch(store, sender, settings) == 1
    assert sender.outbox[0][0] == "+919000000001"

    # Same alert fetched again next cycle -> nothing new goes out
    ingest(raws, store, settings)
    assert dispatch(store, sender, settings) == 0


def test_late_joiners_still_get_a_live_alert(store, settings):
    """Someone who subscribes after the first cycle must not miss a live warning."""
    from commbot.channels.sms import ConsoleSender

    sender = ConsoleSender(quiet=True)
    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)
    assert dispatch(store, sender, settings) == 0      # nobody is subscribed yet

    store.upsert_subscriber(Subscriber("+919000000001", "Bahraich", "hi"))
    assert dispatch(store, sender, settings) == 1      # they get it on the next cycle
    assert dispatch(store, sender, settings) == 0      # and not twice


def test_approval_queue_holds_alert(store, settings):
    from commbot.channels.sms import ConsoleSender

    settings.require_approval = True
    store.upsert_subscriber(Subscriber("+919000000001", "Bahraich", "hi"))
    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)
    assert dispatch(store, ConsoleSender(quiet=True), settings) == 0
    store.set_status("t:DEMO-UP-FLOOD-0001", "approved", reviewed_by="tester")
    assert dispatch(store, ConsoleSender(quiet=True), settings) == 1


# ---------------- messages ----------------

@pytest.mark.parametrize("lang", ["hi", "en"])
def test_sms_fits_budget_and_keeps_helpline(lang):
    facts = extract_facts(parse_cap(load_sample("flood_alert.xml"), source="t")[0])
    msg = render_sms(facts, lang, max_segments=3)
    assert sms_segments(msg) <= 3
    assert "1077" in msg


def test_hindi_counts_as_unicode_sms():
    assert sms_segments("a" * 160) == 1
    assert sms_segments("ब" * 71) == 2


def test_intents():
    assert detect_intent("राहत शिविर कहाँ है") == "shelter"
    assert detect_intent("what is the helpline number") == "helpline"
    assert detect_intent("क्या बाढ़ आ रही है") == "status"
    assert detect_intent("tell me a joke") == "unknown"


# ---------------- feeds ----------------

def test_rss_feed_skips_known_guids(tmp_path):
    from commbot.ingest import fetch_feed

    alert_file = tmp_path / "a.xml"
    alert_file.write_bytes(load_sample("flood_alert.xml"))
    rss = tmp_path / "feed.xml"
    rss.write_text(f"""<rss><channel>
      <item><link>{alert_file}</link><guid isPermaLink="false">DEMO-UP-FLOOD-0001</guid></item>
    </channel></rss>""", encoding="utf-8")

    got = fetch_feed(str(rss), source="t")
    assert len(got) == 1 and got[0].feed_guid == "DEMO-UP-FLOOD-0001"
    # Once we already have it, the alert file isn't even opened.
    assert fetch_feed(str(rss), source="t", is_seen=lambda g: g == "DEMO-UP-FLOOD-0001") == []


def test_real_sachet_alert_with_vague_area(store, settings):
    """Real SACHET quirks: guid != identifier, areaDesc is just 'some parts'."""
    raw = parse_cap(load_sample("sachet_real_thunderstorm.xml"), source="sachet")[0]
    assert raw.source_id == "IN-1789916877126017_17"
    assert "Polygon URL" in raw.parameters

    facts = extract_facts(raw)
    assert facts.hazard == "THUNDERSTORM"
    assert facts.areas == ["East Midnapore", "West Midnapore"]
    assert subscriber_matches(Subscriber("+91", "West Midnapore"), facts)
    assert not subscriber_matches(Subscriber("+91", "Bahraich"), facts)


def test_feed_guid_marked_after_ingest(store, settings):
    raw = parse_cap(load_sample("sachet_real_thunderstorm.xml"), source="sachet")[0]
    raw.feed_guid = "1789916877126017"
    ingest([raw], store, settings)
    assert store.feed_item_seen("sachet", "1789916877126017")
    assert store.alert_seen("sachet:IN-1789916877126017_17")


def test_polygon_file_is_parsed_and_attached(tmp_path):
    """SACHET's polygon file, including a real-world glued-together point."""
    from commbot.ingest import add_polygons, fetch_polygon

    # A square around (21.65, 87.45), plus one malformed pair like the ones
    # that really show up in SACHET files (two points with no space between).
    poly_file = tmp_path / "poly.xml"
    poly_file.write_text(
        "<alert><identifier>IN-1_1</identifier><polygon>"
        "21.60,87.40 21.70,87.40 "
        "21.666943,87.46960121.667775,87.469274 "   # broken pair: dropped, not fatal
        "21.70,87.50 21.60,87.50 21.60,87.40</polygon></alert>",
        encoding="utf-8")

    polygons = fetch_polygon(str(poly_file))
    assert len(polygons) == 1
    assert len(polygons[0]) == 5          # the glued pair was skipped, shape survived
    assert polygons[0][0] == (21.60, 87.40)

    raw = RawAlert(source="sachet", source_id="IN-1_1", event="Thunderstorm",
                   areas=["some parts"], parameters={"Polygon URL": str(poly_file)})
    add_polygons([raw])
    assert raw.polygons == polygons

    # Now a subscriber with GPS inside that shape is matched even though the
    # alert never named their district.
    facts = extract_facts(raw)
    assert subscriber_matches(Subscriber("+91", "unknown", lat=21.65, lon=87.45), facts)
    assert not subscriber_matches(Subscriber("+91", "unknown", lat=28.6, lon=77.2), facts)


# ---------------- inbound SMS ----------------

def test_sms_commands_reply_through_the_gateway(store, settings):
    """A citizen texts the SIM; the reply goes back out the same way."""
    from commbot.channels.sms import ConsoleSender
    from commbot.webhooks import create_app

    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)

    sender = ConsoleSender(quiet=True)
    client = create_app(settings, store, sender).test_client()

    client.post("/sms", json={"event": "sms:received",
                              "payload": {"phoneNumber": "+919000000005",
                                          "message": "JOIN Bahraich EN"}})
    assert "subscribed" in sender.outbox[-1][1]

    client.post("/sms", json={"payload": {"phoneNumber": "+919000000005",
                                          "message": "SHELTER"}})
    assert "Government Inter College" in sender.outbox[-1][1]
    assert sender.outbox[-1][0] == "+919000000005"


def test_inbound_hook_needs_the_token(store, settings):
    from commbot.channels.sms import ConsoleSender
    from commbot.webhooks import create_app

    settings.webhook_token = "letmein"
    client = create_app(settings, store, ConsoleSender(quiet=True)).test_client()
    body = {"payload": {"phoneNumber": "+91", "message": "STOP"}}

    assert client.post("/sms", json=body).status_code == 403
    assert client.post("/sms?token=nope", json=body).status_code == 403
    assert client.post("/sms?token=letmein", json=body).status_code == 200

def test_otps_and_shortcodes_are_ignored(store, settings):
    """The gateway forwards every SMS; bank OTPs must never get a reply."""
    from commbot.channels.sms import ConsoleSender
    from commbot.webhooks import create_app, is_person

    assert is_person("+919876543210")
    assert is_person("9123456789")
    assert not is_person("VM-HDFCBK")
    assert not is_person("57575")

    sender = ConsoleSender(quiet=True)
    client = create_app(settings, store, sender).test_client()
    r = client.post("/sms", json={"payload": {"phoneNumber": "VM-HDFCBK",
                                              "message": "Your OTP is 482913"}})
    assert r.get_json()["ignored"] is True
    assert sender.outbox == []

# ---------------- dashboard ----------------

def test_dashboard_shows_and_approves(store, settings):
    from commbot.webhooks import create_app

    settings.require_approval = True
    store.upsert_subscriber(Subscriber("+919000000001", "Bahraich", "hi"))
    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)

    client = create_app(settings, store).test_client()
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert b"Waiting for approval" in page.data
    assert "बाढ़".encode() in page.data          # Hindi preview of what will be sent

    client.post("/dashboard/review", data={"alert_id": "t:DEMO-UP-FLOOD-0001",
                                           "action": "approve"})
    assert store.get_alert("t:DEMO-UP-FLOOD-0001")["status"] == "approved"


def test_approve_button_posts_inside_the_blueprint(store, settings):
    """The form must point at /dashboard/review, not /review."""
    from commbot.webhooks import create_app

    settings.require_approval = True
    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)

    client = create_app(settings, store).test_client()
    assert b'action="/dashboard/review"' in client.get("/dashboard").data


def test_dashboard_token_is_enforced(store, settings):
    from commbot.webhooks import create_app

    settings.dashboard_token = "letmein"
    client = create_app(settings, store).test_client()

    assert client.get("/dashboard").status_code == 403
    assert client.get("/dashboard?token=wrong").status_code == 403
    assert client.get("/dashboard?token=letmein").status_code == 200


def test_root_goes_to_dashboard(store, settings):
    from commbot.webhooks import create_app

    client = create_app(settings, store).test_client()
    assert client.get("/").headers["Location"].endswith("/dashboard")


# ---------------- android gateway ----------------

def test_android_gateway_sends_the_shape_the_app_expects(monkeypatch, settings):
    from commbot.channels import sms as sms_module

    calls = {}

    class FakeResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"id": "abc123", "state": "Pending"}

    def fake_post(url, json=None, auth=None, timeout=None, **kw):
        calls.update(url=url, json=json, auth=auth)
        return FakeResponse()

    monkeypatch.setattr(sms_module.requests, "post", fake_post)

    settings.sms_provider = "android"
    settings.gateway_url = "http://192.168.1.5:8080"
    settings.gateway_user = "sms"
    settings.gateway_pass = "secret"
    sender = sms_module.get_sender(settings)

    ok, ref = sender.send("+919000000001", "test")
    assert ok and ref == "abc123"
    assert calls["url"] == "http://192.168.1.5:8080/message"
    assert calls["auth"] == ("sms", "secret")
    assert calls["json"] == {"textMessage": {"text": "test"}, "phoneNumbers": ["+919000000001"]}


def test_android_gateway_reports_a_sleeping_phone(monkeypatch, settings):
    from commbot.channels import sms as sms_module

    def fake_post(*a, **kw):
        raise sms_module.requests.RequestException("connection refused")

    monkeypatch.setattr(sms_module.requests, "post", fake_post)
    sender = sms_module.AndroidGatewaySender("http://192.168.1.5:8080", "sms", "secret")
    ok, ref = sender.send("+919000000001", "test")
    assert not ok and "network" in ref

    

def test_nearly_expired_alerts_are_not_pushed(store, settings):
    """Found on a real phone: a warning landed two minutes before it expired."""
    from commbot.prioritize import should_send
    from commbot.utils import to_iso

    facts = extract_facts(parse_cap(load_sample("flood_alert.xml"), source="t")[0])
    sub = Subscriber("+919000000001", "Bahraich", "hi")
    now = now_utc()

    facts.valid_until = to_iso(now + timedelta(minutes=2))
    ok, why = should_send(store, sub, facts, settings, now)
    assert not ok and "expiry" in why

    facts.valid_until = to_iso(now + timedelta(hours=3))
    assert should_send(store, sub, facts, settings, now)[0]


# ---------------- public demo ----------------

def test_demo_mode_is_read_only(store, settings):
    """The hosted copy shows alerts but a visitor can't approve anything."""
    from commbot.demo import DEMO_SUBSCRIBERS, seed_subscribers
    from commbot.webhooks import create_app

    settings.demo_mode = True
    settings.require_approval = True
    seed_subscribers(store)
    assert len(store.list_active_subscribers()) == len(DEMO_SUBSCRIBERS)

    ingest(parse_cap(load_sample("flood_alert.xml"), source="t"), store, settings)
    client = create_app(settings, store).test_client()

    page = client.get("/dashboard").data
    # Sample figures are labelled; the alerts themselves are real, so they aren't.
    assert b"Sample data" in page
    assert b"subscribers are samples" in page
    assert b'action="/dashboard/review"' not in page     # no buttons for visitors

    r = client.post("/dashboard/review", data={"alert_id": "t:DEMO-UP-FLOOD-0001",
                                               "action": "approve"})
    assert r.status_code == 403
    assert store.get_alert("t:DEMO-UP-FLOOD-0001")["status"] == "pending_review"