"""
Optional: mirror alerts to Firestore so a web dashboard (for district
officials or NGO volunteers) can show what's live, pending and sent.

SQLite stays the source of truth. If Firebase is unreachable we log it and
move on. A dashboard outage must never block an alert.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
_db = None


def _client(cred_path: str):
    global _db
    if _db is None:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_path))
        _db = firestore.client()
    return _db


def push_alert(cred_path: str, facts, score: float, status: str) -> None:
    if not cred_path:
        return
    try:
        doc_id = facts.alert_id.replace("/", "_")  # Firestore ids can't contain '/'
        _client(cred_path).collection("alerts").document(doc_id).set({
            **facts.to_dict(),
            "polygons": None,  # nested arrays aren't allowed in Firestore; the dashboard doesn't need them
            "circles": None,
            "score": score,
            "status": status,
        }, merge=True)
    except Exception as exc:
        log.warning("Firebase sync failed for %s: %s", facts.alert_id, exc)
