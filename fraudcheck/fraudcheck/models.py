"""Datamodellen voor een schadecase en de fraudesignalen die erop afgaan."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


def normalize_plate(value: Optional[str]) -> str:
    """Kenteken zonder streepjes en spaties in hoofdletters. 'z-383-hl' -> 'Z383HL'."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def format_plate(value: Optional[str]) -> str:
    """Kenteken met streepjes volgens de Nederlandse sidecodes waar mogelijk."""
    p = normalize_plate(value)
    if len(p) != 6:
        return p
    groups = re.findall(r"[A-Z]+|[0-9]+", p)
    if len(groups) == 3:
        return "-".join(groups)
    if len(groups) == 2:  # bv. 'AB12' + 'CD' komt als 'AB','12','CD' al goed; dit is 4+2 of 2+4
        a, b = groups
        if len(a) == 4:
            return f"{a[:2]}-{a[2:]}-{b}"
        if len(b) == 4:
            return f"{a}-{b[:2]}-{b[2:]}"
    return p


def normalize_phone(value: Optional[str]) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0031"):
        digits = digits[4:]
    elif digits.startswith("31") and len(digits) == 11:
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    return digits


@dataclass
class Attachment:
    name: str
    mime_type: str = ""
    file_id: str = ""
    created: Optional[datetime] = None
    text: str = ""            # tekst uit pdf of formulier (indien gelezen)
    exif_datetime: Optional[datetime] = None
    local_path: str = ""

    @property
    def is_photo(self) -> bool:
        return self.mime_type.startswith("image/") or self.name.lower().endswith((".jpg", ".jpeg", ".png", ".heic"))

    @property
    def is_form(self) -> bool:
        n = self.name.lower()
        if n.startswith(("mail ", "melding ", "fraude-indicatie", "dossieranalyse")):
            return False
        t = (self.text or "").lower()
        return ("formulier" in n or "aanrijding" in n or "europees" in n
                or "aanrijdingsformulier" in t or "schadeaangifte" in t)


@dataclass
class Claim:
    """Alles wat we over een melding weten. Velden komen uit de eFNOL melding en de bijlagen."""
    folder_id: str = ""
    folder_name: str = ""
    verzekerde: str = ""
    kenteken: str = ""
    schadedatum: Optional[date] = None
    schadetijd: Optional[str] = None          # 'HH:MM' als bekend
    gemeld_op: Optional[datetime] = None
    wat_gebeurd: str = ""
    tegenpartij: str = ""
    tegenpartij_kenteken: str = ""
    rijdbaar: str = ""
    toedracht: str = ""
    melder_naam: str = ""
    melder_bedrijf: str = ""
    melder_email: str = ""
    melder_telefoon: str = ""
    referentie_melder: str = ""
    nog_niet_aangeleverd: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    form_fields: dict = field(default_factory=dict)  # uit het schadeformulier gehaalde velden
    raw: dict = field(default_factory=dict)

    @property
    def plate(self) -> str:
        return normalize_plate(self.kenteken)

    @property
    def photos(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_photo]

    @property
    def forms(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_form]


@dataclass
class Signal:
    code: str
    titel: str
    toelichting: str
    gewicht: int
    categorie: str           # Tijdlijn, Historie, Toedracht, Documentatie, Voertuig, Relatie
    hard: bool = False       # harde rode vlag: case altijd minimaal 'Verhoogd'


@dataclass
class CheckResult:
    """Uitkomst van een bron of controle die geen signaal gaf maar wel is uitgevoerd."""
    bron: str
    status: str              # 'ok', 'niet beschikbaar', 'fout'
    detail: str = ""


@dataclass
class Assessment:
    claim: Claim
    score: int
    niveau: str              # Laag, Verhoogd, Hoog
    signals: list[Signal]
    checks: list[CheckResult]
    vervolgacties: list[str]
    gegenereerd_op: datetime
