"""
SQLite storage. No server, one file, works offline, trivially backed up.

For a district-level deployment this is plenty. If you grow to millions of
subscribers, move to Postgres, but keep the same method names so nothing
else has to change.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import timedelta

from .geo import area_matches
from .models import AlertFacts, RawAlert, Subscriber
from .prioritize import SEVERITY_RANK, fingerprint
from .utils import now_utc, to_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    phone       TEXT PRIMARY KEY,
    district    TEXT NOT NULL,
    lang        TEXT NOT NULL DEFAULT 'hi',
    lat         REAL,
    lon         REAL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    raw_json     TEXT NOT NULL,
    facts_json   TEXT NOT NULL,
    score        REAL NOT NULL,
    status       TEXT NOT NULL,   -- pending_review / approved / dispatched / info_only / rejected / cancelled
    created_at   TEXT NOT NULL,
    valid_until  TEXT NOT NULL,
    reviewed_by  TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS deliveries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    phone          TEXT NOT NULL,
    alert_id       TEXT NOT NULL,
    fingerprint    TEXT NOT NULL,
    severity_rank  INTEGER NOT NULL,
    channel        TEXT NOT NULL,
    status         TEXT NOT NULL,   -- sent / failed
    provider_ref   TEXT,
    sent_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_phone ON deliveries(phone, sent_at);

-- Feed items we've already handled, keyed by RSS guid (which can differ
-- from the CAP identifier, so this can't live in the alerts table).
CREATE TABLE IF NOT EXISTS feed_items (
    source      TEXT NOT NULL,
    guid        TEXT NOT NULL,
    handled_at  TEXT NOT NULL,
    PRIMARY KEY (source, guid)
);
"""

# Alerts people can hear about when they ask (SMS STATUS / phone call).
PULLABLE_STATUSES = ("approved", "dispatched", "info_only")


class Store:
    def __init__(self, path: str):
        self.path = path
        # check_same_thread=False because Flask serves requests on threads.
        # The lock below keeps writes from stepping on each other.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")  # lets the web server read while the pipeline writes
        self.conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _exec(self, sql: str, params=()):
        with self._lock, self.conn:
            return self.conn.execute(sql, params)

    def _query(self, sql: str, params=()):
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    # --- subscribers ------------------------------------------------------

    def upsert_subscriber(self, sub: Subscriber) -> None:
        now = to_iso(now_utc())
        self._exec(
            """INSERT INTO subscribers (phone, district, lang, lat, lon, active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(phone) DO UPDATE SET
                   district=excluded.district, lang=excluded.lang,
                   lat=COALESCE(excluded.lat, subscribers.lat),
                   lon=COALESCE(excluded.lon, subscribers.lon),
                   active=1, updated_at=excluded.updated_at""",
            (sub.phone, sub.district, sub.lang, sub.lat, sub.lon, now, now),
        )

    def deactivate_subscriber(self, phone: str) -> None:
        self._exec("UPDATE subscribers SET active=0, updated_at=? WHERE phone=?",
                   (to_iso(now_utc()), phone))

    def get_subscriber(self, phone: str) -> Subscriber | None:
        rows = self._query("SELECT * FROM subscribers WHERE phone=?", (phone,))
        return self._to_sub(rows[0]) if rows else None

    def list_active_subscribers(self) -> list[Subscriber]:
        return [self._to_sub(r) for r in self._query("SELECT * FROM subscribers WHERE active=1")]

    @staticmethod
    def _to_sub(row) -> Subscriber:
        return Subscriber(phone=row["phone"], district=row["district"], lang=row["lang"],
                          lat=row["lat"], lon=row["lon"], active=bool(row["active"]))

    # --- alerts -------------------------------------------------------------

    def alert_seen(self, alert_id: str) -> bool:
        return bool(self._query("SELECT 1 FROM alerts WHERE alert_id=?", (alert_id,)))

    def save_alert(self, raw: RawAlert, facts: AlertFacts, score: float, status: str) -> None:
        self._exec(
            """INSERT OR REPLACE INTO alerts
               (alert_id, source, source_id, raw_json, facts_json, score, status, created_at, valid_until)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (facts.alert_id, raw.source, raw.source_id,
             json.dumps(raw.to_dict(), ensure_ascii=False),
             json.dumps(facts.to_dict(), ensure_ascii=False),
             score, status, to_iso(now_utc()), facts.valid_until),
        )

    def set_status(self, alert_id: str, status: str, reviewed_by: str | None = None) -> bool:
        cur = self._exec(
            "UPDATE alerts SET status=?, reviewed_by=COALESCE(?, reviewed_by) WHERE alert_id=?",
            (status, reviewed_by, alert_id),
        )
        return cur.rowcount > 0

    def cancel_source_ids(self, source: str, source_ids: list[str]) -> int:
        if not source_ids:
            return 0
        marks = ",".join("?" * len(source_ids))
        cur = self._exec(
            f"UPDATE alerts SET status='cancelled' WHERE source=? AND source_id IN ({marks})",
            (source, *source_ids),
        )
        return cur.rowcount

    def get_alert(self, alert_id: str):
        rows = self._query("SELECT * FROM alerts WHERE alert_id=?", (alert_id,))
        return rows[0] if rows else None

    def alerts_with_status(self, status: str) -> list[AlertFacts]:
        rows = self._query(
            "SELECT facts_json FROM alerts WHERE status=? AND valid_until > ? ORDER BY score DESC",
            (status, to_iso(now_utc())),
        )
        return [AlertFacts.from_dict(json.loads(r["facts_json"])) for r in rows]

    def pending_older_than(self, minutes: int):
        cutoff = to_iso(now_utc() - timedelta(minutes=minutes))
        return self._query(
            "SELECT * FROM alerts WHERE status='pending_review' AND created_at <= ?", (cutoff,)
        )

    def list_alerts(self, statuses=None, limit: int = 50):
        if statuses:
            marks = ",".join("?" * len(statuses))
            return self._query(
                f"SELECT * FROM alerts WHERE status IN ({marks}) ORDER BY created_at DESC LIMIT ?",
                (*statuses, limit),
            )
        return self._query("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,))

    def active_alerts(self, district: str | None = None) -> list[AlertFacts]:
        """Alerts a citizen can hear about right now, most important first."""
        marks = ",".join("?" * len(PULLABLE_STATUSES))
        rows = self._query(
            f"""SELECT facts_json FROM alerts
                WHERE status IN ({marks}) AND valid_until > ?
                ORDER BY score DESC""",
            (*PULLABLE_STATUSES, to_iso(now_utc())),
        )
        alerts = [AlertFacts.from_dict(json.loads(r["facts_json"])) for r in rows]
        if district:
            alerts = [a for a in alerts if area_matches(district, a.areas)]
        return alerts

    # --- feed items ---------------------------------------------------------

    def feed_item_seen(self, source: str, guid: str) -> bool:
        return bool(self._query("SELECT 1 FROM feed_items WHERE source=? AND guid=?", (source, guid)))

    def mark_feed_item(self, source: str, guid: str) -> None:
        self._exec("INSERT OR IGNORE INTO feed_items (source, guid, handled_at) VALUES (?, ?, ?)",
                   (source, guid, to_iso(now_utc())))

    # --- deliveries -----------------------------------------------------------

    def record_delivery(self, phone: str, facts: AlertFacts, channel: str, status: str,
                        provider_ref: str, when) -> None:
        self._exec(
            """INSERT INTO deliveries (phone, alert_id, fingerprint, severity_rank, channel,
                                       status, provider_ref, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone, facts.alert_id, fingerprint(facts), SEVERITY_RANK.get(facts.severity, 1),
             channel, status, provider_ref, to_iso(when)),
        )

    def was_delivered(self, phone: str, alert_id: str) -> bool:
        return bool(self._query(
            "SELECT 1 FROM deliveries WHERE phone=? AND alert_id=? AND status='sent'",
            (phone, alert_id),
        ))

    def last_delivery(self, phone: str, fp: str):
        rows = self._query(
            """SELECT * FROM deliveries WHERE phone=? AND fingerprint=? AND status='sent'
               ORDER BY sent_at DESC LIMIT 1""",
            (phone, fp),
        )
        return rows[0] if rows else None

    def recent_deliveries(self, limit: int = 20):
        return self._query("SELECT * FROM deliveries ORDER BY sent_at DESC LIMIT ?", (limit,))

    def delivery_totals(self):
        rows = self._query("SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def count_deliveries_since(self, phone: str, since) -> int:
        rows = self._query(
            "SELECT COUNT(*) AS n FROM deliveries WHERE phone=? AND status='sent' AND sent_at >= ?",
            (phone, to_iso(since)),
        )
        return rows[0]["n"]