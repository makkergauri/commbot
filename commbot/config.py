"""
Central config. Everything comes from environment variables (or a .env file)
so the same code runs on a laptop, a cloud VM, or a Raspberry Pi sitting in a
district control room, without anyone editing Python.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # dotenv is a convenience, not a requirement. Plain env vars work too.
    pass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, "").split(",") if x.strip()]


def _weather_points() -> list[tuple[float, float, str]]:
    # Format: "lat,lon,Name;lat,lon,Name"
    # e.g.    "27.57,81.60,Bahraich;26.76,83.37,Gorakhpur"
    points = []
    for chunk in os.getenv("WEATHER_POINTS", "").split(";"):
        parts = [p.strip() for p in chunk.split(",")]
        if len(parts) >= 3:
            try:
                points.append((float(parts[0]), float(parts[1]), ",".join(parts[2:])))
            except ValueError:
                pass  # skip a bad entry rather than refusing to start
    return points


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("COMMBOT_DB", "commbot.db"))

    # --- Sources ---------------------------------------------------------
    # Comma-separated CAP XML or RSS feed URLs (or local file paths).
    cap_feeds: list[str] = field(default_factory=lambda: _list("CAP_FEEDS"))
    weather_points: list = field(default_factory=_weather_points)
    # SACHET keeps the real geometry in a separate file per alert. Fetching it
    # costs one extra request but gives precise targeting.
    fetch_polygons: bool = field(default_factory=lambda: _bool("FETCH_POLYGONS", True))

    # --- LLM (optional) --------------------------------------------------
    llm_enabled: bool = field(default_factory=lambda: _bool("LLM_ENABLED", False))
    hf_token: str = field(default_factory=lambda: os.getenv("HF_TOKEN", ""))
    hf_model: str = field(
        default_factory=lambda: os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    )

    # --- SMS ---------------------------------------------------------------
    # console | android | http_gateway
    sms_provider: str = field(default_factory=lambda: os.getenv("SMS_PROVIDER", "console"))
    gateway_url: str = field(default_factory=lambda: os.getenv("SMS_GATEWAY_URL", ""))
    gateway_token: str = field(default_factory=lambda: os.getenv("SMS_GATEWAY_TOKEN", ""))
    gateway_user: str = field(default_factory=lambda: os.getenv("SMS_GATEWAY_USER", ""))
    gateway_pass: str = field(default_factory=lambda: os.getenv("SMS_GATEWAY_PASS", ""))

    # --- Decision agent ----------------------------------------------------
    default_lang: str = field(default_factory=lambda: os.getenv("DEFAULT_LANG", "hi"))
    push_threshold: float = field(default_factory=lambda: float(os.getenv("PUSH_THRESHOLD", "6")))
    require_approval: bool = field(default_factory=lambda: _bool("REQUIRE_APPROVAL", True))
    approval_timeout_min: int = field(
        default_factory=lambda: int(os.getenv("APPROVAL_TIMEOUT_MIN", "10"))
    )
    resend_cooldown_min: int = field(
        default_factory=lambda: int(os.getenv("RESEND_COOLDOWN_MIN", "180"))
    )
    max_sms_per_hour: int = field(default_factory=lambda: int(os.getenv("MAX_SMS_PER_HOUR", "4")))
    max_sms_segments: int = field(default_factory=lambda: int(os.getenv("MAX_SMS_SEGMENTS", "3")))

        # Don't push a warning with less time than this left on it. A message
    # saying "valid till 08:30" that lands at 08:28 helps nobody.
    min_minutes_left: int = field(default_factory=lambda: int(os.getenv("MIN_MINUTES_LEFT", "15")))

    # --- Web server --------------------------------------------------------
    # Shared secret the SMS gateway must send with incoming messages, so a
    # stranger who finds the URL can't subscribe or unsubscribe people.
    webhook_token: str = field(default_factory=lambda: os.getenv("WEBHOOK_TOKEN", ""))
    # Shared password for the dashboard. Leave empty only on your own laptop.
    dashboard_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_TOKEN", ""))

    # --- Dashboard sync (optional) ----------------------------------------
    firebase_cred: str = field(default_factory=lambda: os.getenv("FIREBASE_CREDENTIALS", ""))

    poll_interval_sec: int = field(default_factory=lambda: int(os.getenv("POLL_INTERVAL_SEC", "120")))

    # --- Hosting -------------------------------------------------------------
    # DEMO_MODE: read-only public copy with fake subscribers and no real SMS.
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", False))
    # RUN_POLLER: run the fetch loop inside the web process. Needed on hosts
    # that only give you one process; leave off when you run `commbot run`.
    run_poller: bool = field(default_factory=lambda: _bool("RUN_POLLER", False))
