"""Place-name matching and a bit of geometry, with no heavy GIS dependencies."""
from __future__ import annotations

import math
import re

# Words that describe the *type* of place rather than the place itself.
_STOPWORDS = {
    "district", "districts", "dist", "tehsil", "tehsils", "tahsil", "block", "blocks",
    "village", "villages", "city", "and", "of", "area", "areas",
    "जिला", "जनपद", "तहसील", "ब्लॉक", "गांव", "ग्राम", "और",
}

# Replace punctuation explicitly. Don't use [^\w] here: Python doesn't treat
# Devanagari vowel signs (matras) as \w, so that would mangle Hindi names.
_PUNCT = re.compile(r"[,;:/()\[\]\.\-|।&]")


def normalize_place(name: str) -> str:
    cleaned = _PUNCT.sub(" ", (name or "").casefold())
    return " ".join(w for w in cleaned.split() if w not in _STOPWORDS)


def area_matches(district: str, areas: list[str]) -> bool:
    """Does a subscriber's district appear (as whole words) in any alert area?"""
    wanted = normalize_place(district)
    if not wanted:
        return False
    for area in areas:
        # Padding with spaces gives whole-word matching without regex \b,
        # so "Gonda" doesn't accidentally match "Gondal".
        if f" {wanted} " in f" {normalize_place(area)} ":
            return True
    return False


def point_in_polygon(lat: float, lon: float, polygon) -> bool:
    """Classic ray-casting test. Fine for district-sized polygons."""
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        yi, xi = polygon[i]
        yj, xj = polygon[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
