"""Haalt bruikbare velden uit de tekst van een schadeaangifte of Europees aanrijdingsformulier.

De tekst komt uit de OCR van Google Drive of uit pdftotext. Handgeschreven formulieren zijn rommelig
dus alles hier is best effort. Wat we niet vinden laten we leeg en melden we niet als signaal.
"""
from __future__ import annotations

import re
from datetime import date

from .parse_melding import find_plates

_DATE_RE = re.compile(r"\b(\d{1,2})[-/. ](\d{1,2})[-/. ]?(\d{2,4})\b")


def _dates(text: str) -> list[date]:
    out = []
    for d, m, y in _DATE_RE.findall(text):
        y_i = int(y)
        if y_i < 100:
            y_i += 2000
        try:
            out.append(date(y_i, int(m), int(d)))
        except ValueError:
            # '12-112026' achtige OCR: dag-maand aan elkaar
            continue
    # OCR voegt vaak maand en jaar samen: 12-112026
    for d, rest in re.findall(r"\b(\d{1,2})-(\d{6})\b", text):
        try:
            out.append(date(int(rest[2:]), int(rest[:2]), int(d)))
        except ValueError:
            pass
    return out


def parse_form_text(text: str) -> dict:
    t = text or ""
    low = t.lower()
    fields: dict = {}

    m = re.search(r"km[\s.-]*stand[^\d]{0,10}([\d.\s]{3,9})", low)
    if m:
        km = re.sub(r"\D", "", m.group(1))
        if km:
            fields["km_stand"] = int(km)

    m = re.search(r"geboortedatum[^\d]{0,10}(\d{1,2}-\d{1,2}-\d{4})", low)
    if m:
        fields["geboortedatum_bestuurder"] = m.group(1)

    m = re.search(r"datum[,:\s]+(\d{1,2}-\d{1,2}-?\d{4}|\d{1,2}-\d{6})", low)
    if m:
        ds = _dates(m.group(1))
        if ds:
            fields["datum_ondertekening"] = ds[0].isoformat()

    all_dates = sorted({d for d in _dates(t) if 2000 <= d.year <= 2100})
    fields["datums"] = [d.isoformat() for d in all_dates]
    fields["kentekens"] = find_plates(t)

    # Politie: we kijken alleen of er expliciet 'ja' of 'nee' achter de vraag staat (doorhalen is niet leesbaar).
    fields["politie_vermeld"] = bool(re.search(r"politie aanwezig.{0,20}\bja\b(?!/)", low))
    fields["letsel_vermeld"] = bool(re.search(r"aard letsel\s*\S{3,}", low)) and "aard letsel\n" not in low
    fields["alcohol_vermeld"] = bool(re.search(r"drankgebruik.{0,80}\bja\b(?!/)", low, re.S))
    fields["tekst_lengte"] = len(t)
    return fields
