"""Historische schades en fraudedossiers, samengebracht in één doorzoekbare index.

Bronnen die we inlezen
* Claims bordereau van Van Ameyde (sheet 'Project BDX 2.0' of de maandelijkse VA BDX xlsx)
* Eerdere eFNOL cases in de map 0.3.6.30 Schademeldingen documenten
* Fraude registers 'Fraud NL 20xx' (map 0.3.6.19 Fraude)

Elke bron levert rijen als dict. We normaliseren naar ClaimRecord zodat de regels niet hoeven te weten
waar iets vandaan komt.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional

from ..models import normalize_phone, normalize_plate


def _date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s, fmt).date()
            return None if d.year < 1950 else d   # BDX gebruikt 31/12/1899 als leeg
        except ValueError:
            continue
    return None


@dataclass
class ClaimRecord:
    bron: str
    referentie: str
    kenteken: str = ""
    tegenpartij_kenteken: str = ""
    schadedatum: Optional[date] = None
    verzekerde: str = ""
    oorzaak: str = ""
    status: str = ""
    kosten: float = 0.0
    polis_ingang: Optional[date] = None
    polisnummer: str = ""
    fraude_vlag: bool = False
    telefoon: str = ""
    email: str = ""
    folder_id: str = ""


@dataclass
class FraudRecord:
    bron: str
    referentie: str
    kenteken: str = ""
    tegenpartij_kenteken: str = ""
    telefoon: str = ""
    email: str = ""
    naam: str = ""
    categorie: str = ""
    bevestigd: str = ""


# Kolomnamen in de VA bordereau
BDX_MAP = {
    "referentie": "System Number Claim Reference",
    "kenteken": "Vehicle Registration Index",
    "tegenpartij_kenteken": "TP Vehicle Reg",
    "schadedatum": "Incident Date",
    "verzekerde": "Policyholder Name Organisation",
    "oorzaak": "Cause Code 1",
    "status": "Claim Status",
    "kosten": "Total Claim Cost",
    "polis_ingang": "Policy Inception date time",
    "polisnummer": "Policy Number",
    "fraude_vlag": "Fraud Flag",
}

FRAUD_MAP = {
    "referentie": "Claim Number",
    "kenteken": "Vehicle Reg",
    "tegenpartij_kenteken": "Claimant Reg",
    "telefoon": "Telephone",
    "email": "Email",
    "naam": "Policy Holder",
    "categorie": "Fraud Category",
    "bevestigd": "Suspicions Confirmed?",
}


def _money(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) else float(v or 0)
    except ValueError:
        return 0.0


def bdx_rows_to_records(rows: Iterable[dict], bron: str = "BDX Van Ameyde") -> list[ClaimRecord]:
    out = []
    for r in rows:
        g = lambda k: r.get(BDX_MAP[k], "")  # noqa: E731
        plate = normalize_plate(g("kenteken"))
        if not plate:
            continue
        tp = normalize_plate(g("tegenpartij_kenteken"))
        out.append(ClaimRecord(
            bron=bron,
            referentie=str(g("referentie")),
            kenteken=plate,
            tegenpartij_kenteken=tp if len(tp) == 6 else "",
            schadedatum=_date(g("schadedatum")),
            verzekerde=str(g("verzekerde")),
            oorzaak=str(g("oorzaak")),
            status=str(g("status")),
            kosten=_money(g("kosten")),
            polis_ingang=_date(g("polis_ingang")),
            polisnummer=str(g("polisnummer")),
            fraude_vlag=str(g("fraude_vlag")).strip().upper() in ("Y", "YES", "JA", "J"),
        ))
    return out


def fraud_rows_to_records(rows: Iterable[dict], bron: str = "Fraude register") -> list[FraudRecord]:
    out = []
    for r in rows:
        g = lambda k: str(r.get(FRAUD_MAP[k], "") or "")  # noqa: E731
        rec = FraudRecord(
            bron=bron,
            referentie=g("referentie"),
            kenteken=normalize_plate(g("kenteken")),
            tegenpartij_kenteken=normalize_plate(g("tegenpartij_kenteken")),
            telefoon=normalize_phone(g("telefoon")),
            email=g("email").strip().lower(),
            naam=g("naam").strip(),
            categorie=g("categorie"),
            bevestigd=g("bevestigd"),
        )
        if rec.kenteken or rec.telefoon or rec.email or rec.tegenpartij_kenteken:
            out.append(rec)
    return out


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def read_xlsx(path: str, sheet: Optional[str] = None, header_contains: str = "") -> list[dict]:
    """Leest een xlsx. Zoekt de kopregel op de eerste rij die 'header_contains' bevat."""
    import openpyxl  # lazy

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hdr_idx = 0
    if header_contains:
        for i, row in enumerate(rows[:30]):
            if any(header_contains == str(c).strip() for c in row if c is not None):
                hdr_idx = i
                break
    header = [str(c).strip() if c is not None else "" for c in rows[hdr_idx]]
    return [dict(zip(header, row)) for row in rows[hdr_idx + 1:] if any(v not in (None, "") for v in row)]


@dataclass
class HistoryIndex:
    claims: list[ClaimRecord] = field(default_factory=list)
    fraud: list[FraudRecord] = field(default_factory=list)
    bronnen: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._reindex()

    def _reindex(self):
        self.by_plate = defaultdict(list)
        self.by_tp_plate = defaultdict(list)
        self.by_phone = defaultdict(list)
        self.by_email = defaultdict(list)
        for c in self.claims:
            if c.kenteken:
                self.by_plate[c.kenteken].append(c)
            if c.tegenpartij_kenteken:
                self.by_tp_plate[c.tegenpartij_kenteken].append(c)
            if c.telefoon:
                self.by_phone[c.telefoon].append(c)
            if c.email:
                self.by_email[c.email].append(c)

    def add_claims(self, records: list[ClaimRecord], bron: str):
        self.claims.extend(records)
        self.bronnen.append(f"{bron} ({len(records)} schades)")
        self._reindex()

    def add_fraud(self, records: list[FraudRecord], bron: str):
        self.fraud.extend(records)
        self.bronnen.append(f"{bron} ({len(records)} dossiers)")

    # Zoekfuncties -------------------------------------------------------
    def as_insured_vehicle(self, plate: str, exclude_ref: str = "") -> list[ClaimRecord]:
        return [c for c in self.by_plate.get(normalize_plate(plate), []) if c.referentie != exclude_ref]

    def as_third_party(self, plate: str, exclude_ref: str = "") -> list[ClaimRecord]:
        return [c for c in self.by_tp_plate.get(normalize_plate(plate), []) if c.referentie != exclude_ref]

    def fraud_hits(self, plate: str = "", phone: str = "", email: str = "") -> list[tuple[str, FraudRecord]]:
        p, ph, em = normalize_plate(plate), normalize_phone(phone), (email or "").strip().lower()
        hits = []
        for f in self.fraud:
            if p and p in (f.kenteken, f.tegenpartij_kenteken):
                hits.append(("kenteken", f))
            elif ph and len(ph) >= 9 and ph == f.telefoon:
                hits.append(("telefoon", f))
            elif em and em == f.email:
                hits.append(("e-mail", f))
        return hits
