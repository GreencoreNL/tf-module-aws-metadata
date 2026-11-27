"""Leest de 'Melding ... .html' die de eFNOL in de Loxxo Fleet Portal in elke casemap zet."""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Optional

from .models import Claim

# Label in de melding -> veld op Claim. Meerdere labels per veld zodat nieuwe eFNOL versies blijven werken.
LABELS = {
    "verzekerde": "verzekerde",
    "kenteken": "kenteken",
    "schadedatum": "schadedatum",
    "datum schade": "schadedatum",
    "tijdstip": "schadetijd",
    "schadetijd": "schadetijd",
    "tijdstip schade": "schadetijd",
    "wat is er gebeurd": "wat_gebeurd",
    "tegenpartij": "tegenpartij",
    "kenteken tegenpartij": "tegenpartij_kenteken",
    "rijdbaar": "rijdbaar",
    "toedracht": "toedracht",
    "naam": "melder_naam",
    "bedrijf": "melder_bedrijf",
    "e-mail": "melder_email",
    "email": "melder_email",
    "telefoon": "melder_telefoon",
    "referentie melder": "referentie_melder",
    "plaats": "plaats",
    "locatie": "plaats",
    "bestuurder": "bestuurder",
    "letsel": "letsel",
}


class _TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.paragraphs: list[str] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None
        self._p: Optional[list[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "p":
            self._p = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "p" and self._p is not None:
            self.paragraphs.append(" ".join("".join(self._p).split()))
            self._p = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._p is not None:
            self._p.append(data)


def parse_nl_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value: str) -> Optional[str]:
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", value or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse_melding_html(content: str, folder_id: str = "", folder_name: str = "") -> Claim:
    # Bestanden die via de Drive tekst export binnenkomen zijn soms markdown ge-escaped.
    if "\\<" in content:
        content = content.replace("\\<", "<").replace("\\>", ">").replace("\\#", "#").replace("\\&", "&").replace("\\_", "_")
    reader = _TableReader()
    reader.feed(content)

    claim = Claim(folder_id=folder_id, folder_name=folder_name)
    for row in reader.rows:
        if len(row) != 2:
            continue
        label = row[0].strip().lower().rstrip(":")
        value = html.unescape(row[1]).strip()
        claim.raw[row[0].strip()] = value
        attr = LABELS.get(label)
        if not attr:
            continue
        if attr == "schadedatum":
            claim.schadedatum = parse_nl_date(value)
            t = parse_time(value)
            if t and not claim.schadetijd:
                claim.schadetijd = t
        elif attr == "schadetijd":
            claim.schadetijd = parse_time(value)
        else:
            setattr(claim, attr, value)

    # Oudere of handmatige meldingen hebben geen tabel maar regels als 'Kenteken: HHG45Z'
    if not any(len(r) == 2 for r in reader.rows):
        text = re.sub(r"<br\s*/?>", "\n", content)
        text = re.sub(r"</p>|</h\d>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        for line in text.splitlines():
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            label, value = label.strip().lower(), value.strip()
            attr = LABELS.get(label)
            if not attr or not value:
                continue
            claim.raw[label.capitalize()] = value
            if attr == "schadedatum":
                claim.schadedatum = parse_nl_date(value)
            elif attr == "schadetijd":
                claim.schadetijd = parse_time(value)
            else:
                setattr(claim, attr, value)

    for p in reader.paragraphs:
        m = re.search(r"op (\d{1,2}-\d{1,2}-\d{4}) om (\d{1,2}:\d{2})", p)
        if m and "binnengekomen" in p:
            claim.gemeld_op = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%d-%m-%Y %H:%M")
        if p.lower().startswith("nog niet aangeleverd"):
            claim.nog_niet_aangeleverd = p.split(":", 1)[-1].strip()

    from .models import normalize_plate
    claim.tegenpartij_kenteken = normalize_plate(claim.tegenpartij_kenteken)
    # Een kenteken van de tegenpartij in de vrije tekst van de toedracht
    if not claim.tegenpartij_kenteken:
        own = claim.plate
        for cand in find_plates(f"{claim.toedracht} {claim.tegenpartij}"):
            if cand != own:
                claim.tegenpartij_kenteken = cand
                break
    return claim


# Nederlandse kentekens: zes tekens in groepen van 1 tot 3. We eisen streepjes of een herkenbare sidecode.
_PLATE_RE = re.compile(r"\b([A-Z0-9]{1,3})-([A-Z0-9]{2,3})-([A-Z0-9]{1,2})\b|\b([A-Z]{2}\d{2}[A-Z]{2}|\d{2}[A-Z]{2}\d{2}|[A-Z]{2}\d{3}[A-Z]|[A-Z]\d{3}[A-Z]{2}|[A-Z]{3}\d{2}[A-Z]|\d[A-Z]{3}\d{2}|\d{2}[A-Z]{3}\d|[A-Z]{2}\d{2}[A-Z]{2})\b")


def find_plates(text: str) -> list[str]:
    from .models import normalize_plate
    found = []
    for m in _PLATE_RE.finditer((text or "").upper()):
        p = normalize_plate(m.group(0))
        if len(p) == 6 and re.search(r"[A-Z]", p) and re.search(r"\d", p) and p not in found:
            found.append(p)
    return found
