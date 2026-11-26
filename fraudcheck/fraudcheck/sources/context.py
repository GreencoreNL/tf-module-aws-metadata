"""Gegevens over polis en klant uit LoxxoTech Admin en Zoho CRM.

LoxxoTech Admin heeft (nog) geen API voor deze tool. Daarom werkt dit als een eenvoudige lookup die je
vult vanuit een export (CSV of JSON) of vanuit een eigen koppeling. Ontbreekt een bron dan meldt het rapport
dat de controle niet is uitgevoerd in plaats van stilletjes 'geen bijzonderheden'.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..models import normalize_plate
from .history import _date


@dataclass
class PolicyInfo:
    polisnummer: str = ""
    wagenpark: str = ""
    polis_ingang: Optional[date] = None
    polis_einde: Optional[date] = None
    status: str = ""
    voertuig_toegevoegd: Optional[date] = None
    voertuig_afgemeld: Optional[date] = None
    dekking: str = ""


@dataclass
class CustomerInfo:
    naam: str = ""
    klant_sinds: Optional[date] = None
    aantal_voertuigen: Optional[int] = None
    openstaande_facturen: Optional[int] = None
    klachten: Optional[int] = None
    bekend: bool = True


class PolicyLookup:
    def __init__(self, by_plate: Optional[dict[str, PolicyInfo]] = None):
        self.by_plate = by_plate or {}
        self.available = by_plate is not None

    @classmethod
    def from_json(cls, path: str) -> "PolicyLookup":
        """Verwacht {"Z383HL": {"polisnummer": ..., "polis_ingang": "2026-01-01", ...}, ...}"""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        out = {}
        for plate, v in data.items():
            out[normalize_plate(plate)] = PolicyInfo(
                polisnummer=v.get("polisnummer", ""),
                wagenpark=v.get("wagenpark", ""),
                polis_ingang=_date(v.get("polis_ingang")),
                polis_einde=_date(v.get("polis_einde")),
                status=v.get("status", ""),
                voertuig_toegevoegd=_date(v.get("voertuig_toegevoegd")),
                voertuig_afgemeld=_date(v.get("voertuig_afgemeld")),
                dekking=v.get("dekking", ""),
            )
        return cls(out)

    def get(self, plate: str) -> Optional[PolicyInfo]:
        return self.by_plate.get(normalize_plate(plate))


class CustomerLookup:
    """Zoekt de verzekerde op in Zoho CRM (module Accounts = Wagenparken)."""

    def __init__(self, search_fn=None):
        # search_fn(naam) -> Optional[CustomerInfo]. In productie een Zoho API call, in tests een stub.
        self.search_fn = search_fn
        self.available = search_fn is not None

    def get(self, naam: str) -> Optional[CustomerInfo]:
        if not self.search_fn or not naam:
            return None
        return self.search_fn(naam)


def customers_from_json(path: str) -> CustomerLookup:
    """{"Naam verzekerde": {"bekend": true, "klant_sinds": "2025-01-01"}, ...}. Onbekende namen gelden als niet gevonden."""
    with open(path, encoding="utf-8") as fh:
        data = {k.lower(): v for k, v in json.load(fh).items()}

    def search(naam: str):
        v = data.get(naam.lower())
        if v is None:
            return None
        return CustomerInfo(naam=naam, bekend=v.get("bekend", True), klant_sinds=_date(v.get("klant_sinds")))
    return CustomerLookup(search)


def zoho_customer_lookup() -> CustomerLookup:
    """Zoekt in Zoho CRM module Accounts (Wagenparken).

    Nodig: ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN (scope ZohoCRM.modules.accounts.READ)
    en optioneel ZOHO_ACCOUNTS_URL (standaard https://accounts.zoho.eu) en ZOHO_API_URL (https://www.zohoapis.eu).
    """
    import os
    import urllib.parse
    import urllib.request

    acc = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu")
    api = os.environ.get("ZOHO_API_URL", "https://www.zohoapis.eu")
    body = urllib.parse.urlencode({
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"], "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{acc}/oauth/v2/token", data=body), timeout=15) as r:
        token = json.loads(r.read())["access_token"]

    def search(naam: str):
        q = urllib.parse.urlencode({"word": naam[:100], "fields": "Account_Name,Created_Time", "per_page": 5})
        req = urllib.request.Request(f"{api}/crm/v8/Accounts/search?{q}", headers={"Authorization": f"Zoho-oauthtoken {token}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
        rows = json.loads(raw).get("data", []) if raw else []
        if not rows:
            return CustomerInfo(naam=naam, bekend=False)
        return CustomerInfo(naam=rows[0].get("Account_Name", naam), klant_sinds=_date((rows[0].get("Created_Time") or "")[:10]))
    return CustomerLookup(search)


@dataclass
class CoverageInfo:
    """Komt het kenteken voor in de dekkingsbestanden die claims@ naar Carglass en ANWB stuurt."""
    voor_schade: bool = False      # in een dekkingsbestand verstuurd op of voor de schadedatum
    na_schade: bool = False        # alleen in dekkingsbestanden na de schadedatum
    eerst_gezien: Optional[date] = None


class CoverageLookup:
    def __init__(self, by_plate: Optional[dict[str, CoverageInfo]] = None):
        self.by_plate = by_plate or {}
        self.available = by_plate is not None

    @classmethod
    def from_json(cls, path: str) -> "CoverageLookup":
        """{"Z383HL": {"voor_schade": true, "na_schade": true, "eerst_gezien": "2026-07-02"}, "HHG56K": {"voor_schade": false, "na_schade": false}}.
        Neem elk opgezocht kenteken op, ook als het niet gevonden is. Een ontbrekend kenteken geldt als niet opgezocht."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return cls({normalize_plate(k): CoverageInfo(voor_schade=bool(v.get("voor_schade")), na_schade=bool(v.get("na_schade")),
                                                     eerst_gezien=_date(v.get("eerst_gezien"))) for k, v in data.items()})

    def get(self, plate: str) -> Optional[CoverageInfo]:
        return self.by_plate.get(normalize_plate(plate))
