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
    sectie = ""
    for row in reader.rows:
        if len(row) == 1:
            sectie = row[0].strip().lower()
            continue
        if len(row) != 2:
            continue
        label = row[0].strip().lower().rstrip(":")
        value = html.unescape(row[1]).strip()
        if "contactpersoon" in sectie:
            # Contactpersoon verzekerde: niet over de melder heen schrijven
            claim.raw[f"Contactpersoon {row[0].strip().lower()}"] = value
            continue
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


# Sectiekoppen in de melding. Een regel met alleen deze tekst start een nieuwe tabel.
_SECTIES = ("schade", "melder", "contactpersoon verzekerde", "bron")


def melding_pdf_text_to_html(text: str) -> str:
    """Zet de tekst van een Melding .pdf (pdftotext -layout) om naar de HTML vorm die parse_melding_html leest.

    In de PDF staat elke tabelrij als 'Label   waarde' met minstens twee spaties ertussen. Een lange waarde
    loopt door op regels die ver inspringen. Losse tekst ervoor en erna wordt een alinea.
    """
    rows: list[list[str]] = []
    paras: list[str] = []
    in_tabel = False
    kolom = None
    for line in text.splitlines():
        if not line.strip():
            if not in_tabel and paras and paras[-1]:
                paras.append("")
            continue
        stripped = line.strip()
        if stripped.lower() in _SECTIES:
            rows.append([stripped])
            in_tabel = True
            continue
        if in_tabel and rows and len(rows[-1]) == 2 and kolom and len(line) - len(line.lstrip()) >= kolom - 2:
            rows[-1][1] += " " + stripped
            continue
        m = re.match(r"^(\s*)(\S.*?)\s{2,}(\S.*)$", line)
        if in_tabel and not m:
            # Smalle kolommen: label en waarde met maar één spatie. Herken dan het bekende label.
            low = stripped.lower()
            bekend = next((lab for lab in sorted(LABELS, key=len, reverse=True) if low.startswith(lab + " ")), None)
            if bekend:
                rows.append([stripped[:len(bekend)], stripped[len(bekend):].strip()])
                kolom = None
                continue
        if in_tabel and m and len(m.group(2)) <= 40:
            kolom = line.index(m.group(3), len(m.group(1)) + len(m.group(2)))
            rows.append([m.group(2).strip(), m.group(3).strip()])
            continue
        if in_tabel and rows and len(rows[-1]) == 2 and not m and len(stripped) <= 40 and line.startswith(" "):
            # label zonder waarde
            rows.append([stripped, ""])
            continue
        in_tabel = False
        if paras and paras[-1]:
            # Afgebroken op een streepje (zoals in een datum) zonder spatie verder
            paras[-1] += ("" if paras[-1].endswith("-") else " ") + stripped
        else:
            if paras and paras[-1] == "":
                paras[-1] = stripped
            else:
                paras.append(stripped)
    e = html.escape
    body = "".join(f"<p>{e(p)}</p>" for p in paras if p)
    trs = "".join(f"<tr><th>{e(r[0])}</th></tr>" if len(r) == 1 else f"<tr><td>{e(r[0])}</td><td>{e(r[1])}</td></tr>" for r in rows)
    return f"<html><body>{body}<table>{trs}</table></body></html>"


def pdf_text(path: str) -> str:
    """Tekst uit een PDF met behoud van kolommen. Gebruikt pdftotext (poppler), en anders pypdf."""
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
    from pypdf import PdfReader  # pragma: no cover
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in PdfReader(str(path)).pages)


def parse_melding_pdf(path: str, folder_id: str = "", folder_name: str = "") -> Claim:
    return parse_melding_html(melding_pdf_text_to_html(pdf_text(path)), folder_id=folder_id, folder_name=folder_name)


def parse_melding_file(path, folder_id: str = "", folder_name: str = "") -> Claim:
    """Leest een Melding .html (oud) of .pdf (nieuw)."""
    from pathlib import Path
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return parse_melding_pdf(str(p), folder_id, folder_name)
    return parse_melding_html(p.read_text(encoding="utf-8"), folder_id, folder_name)
