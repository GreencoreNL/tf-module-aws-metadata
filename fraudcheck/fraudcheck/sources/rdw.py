"""RDW Open Data (opendata.rdw.nl). Geen sleutel nodig."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Optional

from ..models import normalize_plate

BASE = "https://opendata.rdw.nl/resource/m9d7-ebf2.json"


def _d(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


class RDWClient:
    def __init__(self, timeout: int = 15, cache: Optional[dict] = None):
        self.timeout = timeout
        self.cache = cache if cache is not None else {}

    def lookup(self, plate: str) -> Optional[dict]:
        """Geeft het RDW record terug, None als het kenteken niet bestaat. Gooit bij netwerkfouten."""
        p = normalize_plate(plate)
        if not p:
            return None
        if p in self.cache:
            return self.cache[p]
        url = f"{BASE}?{urllib.parse.urlencode({'kenteken': p})}"
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        rec = rows[0] if rows else None
        if rec:
            rec = dict(rec)
            rec["_datum_tenaamstelling"] = _d(rec.get("datum_tenaamstelling"))
            rec["_datum_eerste_toelating"] = _d(rec.get("datum_eerste_toelating"))
            rec["_datum_eerste_tenaamstelling_nl"] = _d(rec.get("datum_eerste_tenaamstelling_in_nederland"))
            rec["_vervaldatum_apk"] = _d(rec.get("vervaldatum_apk"))
        self.cache[p] = rec
        return rec
