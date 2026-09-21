"""
Plain data containers. Keeping these dumb (no network, no DB) makes the rest
of the code easy to test.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class RawAlert:
    """An alert exactly as it arrived from a source, before interpretation."""

    source: str                 # e.g. "sachet.ndma.gov.in", "open-meteo", "local"
    source_id: str              # unique id from the source, used for dedup
    title: str = ""
    body: str = ""
    instruction: str = ""
    event: str = ""
    sender_name: str = ""
    severity: str = "Unknown"   # CAP words: Extreme / Severe / Moderate / Minor / Unknown
    urgency: str = "Unknown"    # Immediate / Expected / Future / Past / Unknown
    certainty: str = "Unknown"  # Observed / Likely / Possible / Unlikely / Unknown
    areas: list[str] = field(default_factory=list)
    polygons: list = field(default_factory=list)   # list of [(lat, lon), ...]
    circles: list = field(default_factory=list)    # list of (lat, lon, radius_km)
    sent: str = ""
    expires: str = ""
    language: str = "en"
    msg_type: str = "Alert"     # Alert / Update / Cancel
    references: list[str] = field(default_factory=list)
    official: bool = True       # False for model forecasts etc.
    feed_guid: str = ""         # RSS <guid> it came from (NOT always equal to source_id!)
    parameters: dict = field(default_factory=dict)  # CAP <parameter> name -> value

    def full_text(self) -> str:
        parts = (self.event, self.title, self.body, self.instruction, " ; ".join(self.areas))
        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AlertFacts:
    """
    The structured, validated version of an alert. Outgoing messages are
    built ONLY from these fields, never from free LLM text.
    """

    alert_id: str
    hazard: str
    severity: str
    urgency: str
    certainty: str
    areas: list[str]
    actions: list[str]
    helplines: list[str]
    shelters: list[str]
    valid_until: str
    headline: str = ""
    source_name: str = ""
    official: bool = True
    polygons: list = field(default_factory=list)
    circles: list = field(default_factory=list)
    extraction_method: str = "rules"   # "rules" or "llm"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AlertFacts":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Subscriber:
    phone: str
    district: str
    lang: str = "hi"
    lat: Optional[float] = None
    lon: Optional[float] = None
    active: bool = True