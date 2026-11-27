"""Alle fraude indicatoren. Elke regel is een functie die signalen teruggeeft.

Gewichten staan in WEIGHTS zodat de claims afdeling ze kan bijstellen zonder de logica te raken.
Een signaal is een aanwijzing en nooit een conclusie. De score bepaalt alleen of een case extra aandacht krijgt.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from .models import Claim, CheckResult, Signal, format_plate, normalize_phone, normalize_plate
from .sources.context import CoverageLookup, CustomerLookup, PolicyLookup
from .sources.history import HistoryIndex
from .sources.rdw import RDWClient

WEIGHTS = {
    # Tijdlijn
    "T01_schadedatum_na_melding": 40,
    "T02_nachtelijk_tijdstip": 12,
    "T03_late_melding_7": 4,
    "T03_late_melding_14": 8,
    "T03_late_melding_30": 15,
    "T04_kort_na_polisingang_30": 25,
    "T04_kort_na_polisingang_90": 12,
    "T05_kort_na_toevoegen_voertuig": 20,
    "T06_na_einde_dekking": 35,
    "T07_recent_tenaamgesteld": 15,
    "T08_weekend_feestdag": 3,
    "T09_datum_formulier_wijkt_af": 15,
    # Historie
    "H01_kenteken_eerder_schade_1": 8,
    "H01_kenteken_eerder_schade_2plus": 18,
    "H02_kenteken_als_tegenpartij": 20,
    "H03_tegenpartij_vaker_betrokken": 18,
    "H04_fraude_register": 45,
    "H05_eerder_fraudevlag": 30,
    "H06_contactgegevens_bij_andere_verzekerden": 15,
    "H07_zelfde_partijen_eerder": 30,
    # Toedracht
    "D01_toedracht_te_kort": 12,
    "D02_toedracht_vaag": 10,
    "D03_toedracht_past_niet_bij_type": 10,
    "D04_kop_staart_zonder_details": 6,
    "D05_alleen_tegenpartij_schuld": 4,
    # Documentatie
    "A01_geen_fotos": 10,
    "A02_geen_formulier_bij_tegenpartij": 10,
    "A03_foto_ouder_dan_schade": 25,
    "A04_foto_na_melding_zonder_exif": 0,
    "A05_tegenpartij_kenteken_onbekend": 6,
    # Voertuig
    "V01_kenteken_onbekend_rdw": 35,
    "V02_geen_wam_rdw": 25,
    "V03_tellerstand_onlogisch": 12,
    "V04_export": 20,
    "V05_apk_verlopen": 6,
    "V06_hoge_waarde_niet_rijdbaar": 5,
    "V07_niet_in_dekkingsbestand": 25,
    "V08_pas_na_schade_in_dekkingsbestand": 35,
    "V09_kort_voor_schade_in_dekkingsbestand": 15,
    # Relatie
    "R01_verzekerde_onvolledig": 6,
    "R04_melder_freemail_zakelijk": 3,
    # Gevonden bij het lezen van de stukken (signalen.json in de casemap)
    "S01_rol_tegenstrijdig_met_pv": 40,
    "S02_alcohol_of_drugs": 30,
    "S03_plaats_ongeval_verlaten": 25,
    "S04_toedracht_tegenstrijdig_met_stukken": 20,
    "S05_eenzijdig_ongeval_met_letselclaim": 10,
    "S06_tenaamstelling_direct_na_schade": 10,
    "S07_telefoongebruik": 10,
    "S08_foto_ander_voertuig": 40,
}

NACHT_START, NACHT_EIND = 22, 6
VAGE_WOORDEN = ["weet niet", "onbekend", "geen idee", "geen flauw", "ineens", "opeens", "zomaar",
                "plotseling schade", "ontdekt", "aangetroffen", "niet gezien", "kan ik niet zeggen"]
FREEMAIL = ("gmail.", "hotmail.", "outlook.", "live.", "yahoo.", "icloud.", "ziggo.nl", "kpnmail.nl", "planet.nl")


def _sig(code: str, titel: str, toelichting: str, categorie: str, hard: bool = False) -> Signal:
    return Signal(code=code, titel=titel, toelichting=toelichting, gewicht=WEIGHTS[code], categorie=categorie, hard=hard)


# --------------------------------------------------------------------------- feestdagen
def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nl_feestdagen(year: int) -> dict[date, str]:
    e = _easter(year)
    koningsdag = date(year, 4, 27)
    if koningsdag.weekday() == 6:
        koningsdag = date(year, 4, 26)
    return {
        date(year, 1, 1): "Nieuwjaarsdag", e - timedelta(days=2): "Goede Vrijdag", e: "Eerste Paasdag",
        e + timedelta(days=1): "Tweede Paasdag", koningsdag: "Koningsdag", date(year, 5, 5): "Bevrijdingsdag",
        e + timedelta(days=39): "Hemelvaartsdag", e + timedelta(days=49): "Eerste Pinksterdag",
        e + timedelta(days=50): "Tweede Pinksterdag", date(year, 12, 25): "Eerste Kerstdag",
        date(year, 12, 26): "Tweede Kerstdag", date(year, 12, 31): "Oudejaarsdag",
    }


# --------------------------------------------------------------------------- context voor regels
class RuleContext:
    def __init__(self, history: Optional[HistoryIndex] = None, rdw: Optional[RDWClient] = None,
                 policies: Optional[PolicyLookup] = None, customers: Optional[CustomerLookup] = None,
                 coverage: Optional[CoverageLookup] = None,
                 today: Optional[date] = None):
        self.history = history
        self.rdw = rdw
        self.policies = policies
        self.customers = customers
        self.coverage = coverage
        self.today = today or date.today()
        self.checks: list[CheckResult] = []
        self.rdw_record: Optional[dict] = None


def is_claim_derde(claim: Claim) -> bool:
    """Aansprakelijkstelling of claim van een derde (tegenpartij, haar verzekeraar of belangenbehartiger)."""
    t = f"{claim.wat_gebeurd} {claim.melder_bedrijf}".lower()
    return any(k in t for k in ("aansprakelijkstelling", "claim van een derde", "verzekeraar tegenpartij", "belangenbehartiger"))


def heeft_expertise(claim: Claim) -> bool:
    """Een expertiserapport of schadecalculatie bevat vrijwel altijd foto's van de schade."""
    for a in claim.attachments:
        t = (a.text or "").lower()
        if any(k in t for k in ("expertiserapport", "schade-calculatie", "s c h a d e - c a l c u l a t i e", "eindcalculatie")):
            return True
    return False


# --------------------------------------------------------------------------- tijdlijn
def rule_tijdlijn(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    sd, gm = claim.schadedatum, claim.gemeld_op
    if not sd:
        out.append(Signal("T00", "Schadedatum ontbreekt of is onleesbaar", "Zonder schadedatum kan de tijdlijn niet worden getoetst.", 10, "Tijdlijn"))
        return out
    ref = gm.date() if gm else ctx.today
    if sd > ref:
        out.append(_sig("T01_schadedatum_na_melding", "Schadedatum ligt na het moment van melden",
                        f"Schadedatum {sd:%d-%m-%Y} terwijl de melding binnenkwam op {ref:%d-%m-%Y}. Een schade kan niet worden gemeld voordat hij is gebeurd.",
                        "Tijdlijn", hard=True))
    else:
        days = (ref - sd).days
        # Een verzekeraar of belangenbehartiger van een derde claimt pas na de eigen expertise. Alleen echt laat telt dan.
        if is_claim_derde(claim) and days <= 90:
            days = 0
        if days > 30:
            out.append(_sig("T03_late_melding_30", "Schade pas na meer dan 30 dagen gemeld", f"{days} dagen tussen schade en melding.", "Tijdlijn"))
        elif days > 14:
            out.append(_sig("T03_late_melding_14", "Schade pas na meer dan 14 dagen gemeld", f"{days} dagen tussen schade en melding.", "Tijdlijn"))
        elif days > 7:
            out.append(_sig("T03_late_melding_7", "Schade pas na meer dan een week gemeld", f"{days} dagen tussen schade en melding.", "Tijdlijn"))

    if claim.schadetijd:
        hh = int(claim.schadetijd[:2])
        if hh >= NACHT_START or hh < NACHT_EIND:
            out.append(_sig("T02_nachtelijk_tijdstip", "Schade 's nachts", f"Tijdstip {claim.schadetijd} valt tussen 22:00 en 06:00.", "Tijdlijn"))
    else:
        ctx.checks.append(CheckResult("Tijdstip schade", "niet beschikbaar", "De eFNOL vraagt nog geen tijdstip uit. Nachtelijk tijdstip is daarom niet getoetst."))

    fd = nl_feestdagen(sd.year).get(sd)
    if fd or sd.weekday() >= 5:
        out.append(_sig("T08_weekend_feestdag", "Schade in het weekend of op een feestdag",
                        fd or ("zaterdag" if sd.weekday() == 5 else "zondag"), "Tijdlijn"))

    # Datum op het formulier tegenover de datum in de melding
    datums = []
    for a in claim.forms:
        datums += claim.form_fields.get(a.name, {}).get("datums", [])
    if datums:
        # Geboortedata en oude datums negeren, alleen datums rond de schade tellen mee
        ds = [d for d in (date.fromisoformat(x) for x in datums) if abs((d - sd).days) <= 120]
        if ds and sd not in ds:
            nearest = min(ds, key=lambda d: abs((d - sd).days))
            if abs((nearest - sd).days) >= 2:
                out.append(_sig("T09_datum_formulier_wijkt_af", "Datum op formulier wijkt af van schadedatum",
                                f"Melding noemt {sd:%d-%m-%Y}, formulier noemt {', '.join(d.strftime('%d-%m-%Y') for d in ds)}.", "Tijdlijn"))
    return out


def rule_polis(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    pol = ctx.policies.get(claim.kenteken) if ctx.policies and ctx.policies.available else None
    # Terugvallen op de BDX als admin data ontbreekt
    if not pol and ctx.history:
        prev = [c for c in ctx.history.as_insured_vehicle(claim.kenteken) if c.polis_ingang]
        if prev:
            from .sources.context import PolicyInfo
            pol = PolicyInfo(polisnummer=prev[-1].polisnummer, polis_ingang=prev[-1].polis_ingang)
    if not pol:
        ctx.checks.append(CheckResult("Polis (LoxxoTech Admin)", "niet beschikbaar",
                                      "Ingangsdatum polis en datum toevoegen voertuig niet getoetst. Controleer handmatig in de admin."))
        return out
    ctx.checks.append(CheckResult("Polis (LoxxoTech Admin)", "ok", f"Polis {pol.polisnummer or 'onbekend'} ingang {pol.polis_ingang or 'onbekend'}"))
    sd = claim.schadedatum
    if not sd:
        return out
    if pol.polis_ingang:
        d = (sd - pol.polis_ingang).days
        if 0 <= d <= 30:
            out.append(_sig("T04_kort_na_polisingang_30", "Schade binnen 30 dagen na ingang polis", f"{d} dagen na ingang {pol.polis_ingang:%d-%m-%Y}.", "Tijdlijn"))
        elif 0 <= d <= 90:
            out.append(_sig("T04_kort_na_polisingang_90", "Schade binnen 90 dagen na ingang polis", f"{d} dagen na ingang {pol.polis_ingang:%d-%m-%Y}.", "Tijdlijn"))
        elif d < 0:
            out.append(_sig("T06_na_einde_dekking", "Schade voor ingang polis", f"Polis ging pas in op {pol.polis_ingang:%d-%m-%Y}.", "Tijdlijn", hard=True))
    if pol.voertuig_toegevoegd:
        d = (sd - pol.voertuig_toegevoegd).days
        if 0 <= d <= 30:
            out.append(_sig("T05_kort_na_toevoegen_voertuig", "Voertuig kort voor de schade aan de polis toegevoegd",
                            f"Toegevoegd op {pol.voertuig_toegevoegd:%d-%m-%Y}, {d} dagen voor de schade.", "Tijdlijn"))
        elif d < 0:
            out.append(_sig("T06_na_einde_dekking", "Voertuig stond op schadedatum nog niet op de polis",
                            f"Toegevoegd op {pol.voertuig_toegevoegd:%d-%m-%Y}.", "Tijdlijn", hard=True))
    for einde, label in ((pol.polis_einde, "polis"), (pol.voertuig_afgemeld, "voertuig")):
        if einde and sd > einde:
            out.append(_sig("T06_na_einde_dekking", f"Schade na einde dekking ({label})", f"Einde {einde:%d-%m-%Y}.", "Tijdlijn", hard=True))
    return out


# --------------------------------------------------------------------------- historie
def _recent(records, sd: Optional[date], months: int = 36):
    if not sd:
        return records
    lo = sd - timedelta(days=months * 30)
    return [r for r in records if not r.schadedatum or lo <= r.schadedatum <= sd + timedelta(days=1)]


def _fmt_refs(records, n=4) -> str:
    parts = []
    for r in records[:n]:
        d = r.schadedatum.strftime("%d-%m-%Y") if r.schadedatum else "datum onbekend"
        parts.append(f"{r.referentie or r.bron} ({d}{', ' + r.oorzaak if r.oorzaak else ''})")
    more = f" en {len(records) - n} meer" if len(records) > n else ""
    return "; ".join(parts) + more


def rule_historie(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    h = ctx.history
    if not h:
        ctx.checks.append(CheckResult("Schadehistorie", "niet beschikbaar", "Geen BDX of eerdere cases geladen."))
        return out
    ctx.checks.append(CheckResult("Schadehistorie", "ok", "Doorzocht: " + "; ".join(h.bronnen)))
    own_ref = claim.folder_id
    plate, tp = claim.plate, normalize_plate(claim.tegenpartij_kenteken)

    # Dezelfde schade kan al in de BDX staan. Een record op exact dezelfde datum tellen we niet als eerdere schade.
    prev = [r for r in _recent(h.as_insured_vehicle(plate), claim.schadedatum)
            if r.folder_id != own_ref and r.schadedatum != claim.schadedatum]
    if len(prev) >= 2:
        out.append(_sig("H01_kenteken_eerder_schade_2plus", f"Kenteken had al {len(prev)} schades in 3 jaar", _fmt_refs(prev), "Historie"))
    elif len(prev) == 1:
        out.append(_sig("H01_kenteken_eerder_schade_1", "Kenteken had al een schade in 3 jaar", _fmt_refs(prev), "Historie"))

    as_tp = [r for r in h.as_third_party(plate) if r.folder_id != own_ref]
    if as_tp:
        out.append(_sig("H02_kenteken_als_tegenpartij", "Kenteken komt ook voor als tegenpartij in andere schades",
                        _fmt_refs(as_tp), "Historie"))

    if tp:
        tp_hist = [r for r in h.as_third_party(tp) + h.as_insured_vehicle(tp) if r.folder_id != own_ref]
        if tp_hist:
            out.append(_sig("H03_tegenpartij_vaker_betrokken", f"Tegenpartij {format_plate(tp)} was al bij andere schades betrokken",
                            _fmt_refs(tp_hist), "Historie"))
        same = [r for r in h.as_insured_vehicle(plate) if r.tegenpartij_kenteken == tp and r.schadedatum != claim.schadedatum]
        same += [r for r in h.as_insured_vehicle(tp) if r.tegenpartij_kenteken == plate]
        if same:
            out.append(_sig("H07_zelfde_partijen_eerder", "Dezelfde twee voertuigen botsten eerder ook al",
                            _fmt_refs(same), "Historie", hard=True))

    flagged = [r for r in h.as_insured_vehicle(plate) if r.fraude_vlag]
    if flagged:
        out.append(_sig("H05_eerder_fraudevlag", "Eerdere schade op dit kenteken had een fraudevlag", _fmt_refs(flagged), "Historie"))

    hits = h.fraud_hits(plate=plate, phone=claim.melder_telefoon, email=claim.melder_email)
    if tp:
        hits += [(f"tegenpartij {k}", f) for k, f in h.fraud_hits(plate=tp)]
    if hits:
        txt = "; ".join(f"{k} komt voor in {f.bron} {f.referentie} ({f.categorie or 'categorie onbekend'})" for k, f in hits[:4])
        out.append(_sig("H04_fraude_register", "Match in het fraude register", txt, "Historie", hard=True))
    if h.fraud:
        ctx.checks.append(CheckResult("Fraude register", "ok", f"{len(h.fraud)} {'dossier' if len(h.fraud) == 1 else 'dossiers'} doorzocht op kenteken, telefoon en e-mail"))

    # Zelfde telefoon of e-mail bij meldingen voor andere verzekerden
    others = set()
    ph, em = normalize_phone(claim.melder_telefoon), (claim.melder_email or "").lower()
    for r in (h.by_phone.get(ph, []) if ph else []) + (h.by_email.get(em, []) if em else []):
        if r.folder_id != own_ref and r.verzekerde and r.verzekerde.lower() != claim.verzekerde.lower() and r.kenteken != plate:
            others.add(f"{r.verzekerde} ({format_plate(r.kenteken)})")
    if others:
        out.append(_sig("H06_contactgegevens_bij_andere_verzekerden", "Melder gebruikte dezelfde contactgegevens bij andere verzekerden",
                        ", ".join(sorted(others)[:5]), "Historie"))
    return out


# --------------------------------------------------------------------------- toedracht
def rule_toedracht(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    t = (claim.toedracht or "").strip()
    words = re.findall(r"\w+", t)
    if len(words) < 6:
        out.append(_sig("D01_toedracht_te_kort", "Toedracht is te summier",
                        f"'{t or '(leeg)'}' is {len(words)} woorden. Een bruikbare toedracht beschrijft plaats, rijrichting en wat er gebeurde.",
                        "Toedracht"))
    low = t.lower()
    vaag = [w for w in VAGE_WOORDEN if w in low]
    if vaag:
        out.append(_sig("D02_toedracht_vaag", "Toedracht bevat vage formuleringen", ", ".join(vaag), "Toedracht"))

    wat = (claim.wat_gebeurd or "").lower()
    tegen = (claim.tegenpartij or "").lower()
    if "ander voertuig" in wat and tegen.startswith("nee"):
        out.append(_sig("D03_toedracht_past_niet_bij_type", "Aanrijding met ander voertuig maar geen tegenpartij",
                        f"Type '{claim.wat_gebeurd}', tegenpartij '{claim.tegenpartij}'.", "Toedracht"))
    if any(k in wat for k in ("diefstal", "inbraak")) and any(k in low for k in ("aanrijding", "botsing", "kop staart")):
        out.append(_sig("D03_toedracht_past_niet_bij_type", "Toedracht past niet bij het type schade",
                        f"Type '{claim.wat_gebeurd}' maar toedracht beschrijft een aanrijding.", "Toedracht"))
    if re.search(r"kop[\s-]?staart|achterop", low) and len(words) < 10:
        out.append(_sig("D04_kop_staart_zonder_details", "Kop staart botsing zonder details",
                        "Kop staart is de meest gebruikte toedracht bij geënsceneerde aanrijdingen. Vraag om locatie, snelheid en verkeerssituatie.",
                        "Toedracht"))
    if re.search(r"tegen mij aan|op mij in|achterop mij|tegenpartij (reed|is)", low) and "stil" in low:
        out.append(_sig("D05_alleen_tegenpartij_schuld", "Melder stond stil en tegenpartij is volledig schuldig",
                        "Veel voorkomend patroon. Op zichzelf geen probleem maar check of het formulier dit bevestigt.", "Toedracht"))
    return out


# --------------------------------------------------------------------------- documentatie
def rule_documentatie(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    wat = (claim.wat_gebeurd or "").lower()
    tegen = (claim.tegenpartij or "").lower()
    if not claim.photos and not heeft_expertise(claim):
        out.append(_sig("A01_geen_fotos", "Geen foto's van de schade",
                        f"Volgens de melding nog niet aangeleverd: {claim.nog_niet_aangeleverd}." if claim.nog_niet_aangeleverd
                        else "Er zijn geen afbeeldingen in de casemap gevonden.", "Documentatie"))
    if tegen.startswith("ja") and not claim.forms:
        out.append(_sig("A02_geen_formulier_bij_tegenpartij", "Tegenpartij bekend maar geen schadeformulier in de map",
                        f"Melder gaf aan: '{claim.tegenpartij}'.", "Documentatie"))
    if tegen.startswith("ja") and not claim.tegenpartij_kenteken:
        kentekens = [p for a in claim.forms for p in claim.form_fields.get(a.name, {}).get("kentekens", []) if p != claim.plate]
        if kentekens:
            claim.tegenpartij_kenteken = kentekens[0]
        else:
            out.append(_sig("A05_tegenpartij_kenteken_onbekend", "Kenteken tegenpartij niet vastgelegd",
                            "Niet in de melding en niet leesbaar op het formulier. Zonder kenteken is de tegenpartij niet te toetsen.", "Documentatie"))
    exif_checked = False
    for p in claim.photos:
        if p.exif_datetime and claim.schadedatum:
            exif_checked = True
            if p.exif_datetime.date() < claim.schadedatum - timedelta(days=1):
                out.append(_sig("A03_foto_ouder_dan_schade", "Foto is gemaakt voor de schadedatum",
                                f"{p.name} heeft opnamedatum {p.exif_datetime:%d-%m-%Y %H:%M}, schadedatum is {claim.schadedatum:%d-%m-%Y}. Mogelijk oude schade.",
                                "Documentatie", hard=True))
    if claim.photos:
        ctx.checks.append(CheckResult("Foto metadata", "ok" if exif_checked else "niet beschikbaar",
                                      "Opnamedatum vergeleken met schadedatum" if exif_checked else "Foto's bevatten geen opnamedatum (vaak na doorsturen via WhatsApp of mail)."))
    return out


# --------------------------------------------------------------------------- voertuig (RDW)
def rule_voertuig(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    if not ctx.rdw:
        ctx.checks.append(CheckResult("RDW", "niet beschikbaar", "RDW niet geraadpleegd."))
        return out
    try:
        rec = ctx.rdw.lookup(claim.kenteken)
    except Exception as exc:  # netwerk
        ctx.checks.append(CheckResult("RDW", "fout", str(exc)))
        return out
    ctx.rdw_record = rec
    if rec is None:
        out.append(_sig("V01_kenteken_onbekend_rdw", "Kenteken bestaat niet bij de RDW",
                        f"'{claim.kenteken}' geeft geen resultaat. Tikfout of vals kenteken.", "Voertuig", hard=True))
        ctx.checks.append(CheckResult("RDW", "ok", "Kenteken niet gevonden"))
        return out
    ctx.checks.append(CheckResult("RDW", "ok", f"{rec.get('merk', '')} {rec.get('handelsbenaming', '')}, {rec.get('voertuigsoort', '')}, eerste toelating {rec.get('_datum_eerste_toelating') or '?'}"))
    sd = claim.schadedatum
    tn = rec.get("_datum_tenaamstelling")
    # De huidige WAM status zegt alleen iets als het voertuig sinds de schade niet van eigenaar is gewisseld
    if rec.get("wam_verzekerd", "").lower() == "nee" and not (tn and sd and tn > sd):
        out.append(_sig("V02_geen_wam_rdw", "RDW registreert geen WAM verzekering", "Volgens RDW is het voertuig nu niet WAM verzekerd.", "Voertuig"))
    if tn and sd and 0 <= (sd - tn).days <= 90:
        out.append(_sig("T07_recent_tenaamgesteld", "Voertuig kort voor de schade op naam gezet",
                        f"Tenaamstelling {tn:%d-%m-%Y}, {(sd - tn).days} dagen voor de schade.", "Voertuig"))
    elif tn and sd and tn > sd:
        ctx.checks.append(CheckResult("RDW tenaamstelling", "ok", f"Voertuig is na de schade ({tn:%d-%m-%Y}) op een nieuwe naam gezet. Controleer of verzekerde nog eigenaar is."))
    oordeel = (rec.get("tellerstandoordeel") or "").lower()
    if "onlogisch" in oordeel:
        out.append(_sig("V03_tellerstand_onlogisch", "RDW oordeel tellerstand is onlogisch", rec.get("tellerstandoordeel"), "Voertuig"))
    if (rec.get("export_indicator") or "").lower() == "ja":
        out.append(_sig("V04_export", "Voertuig staat geregistreerd voor export", "RDW export indicator staat op Ja.", "Voertuig", hard=True))
    apk = rec.get("_vervaldatum_apk")
    if apk and sd and apk < sd:
        out.append(_sig("V05_apk_verlopen", "APK was verlopen op schadedatum", f"APK verliep {apk:%d-%m-%Y}.", "Voertuig"))
    try:
        cat = int(rec.get("catalogusprijs") or 0)
    except ValueError:
        cat = 0
    if cat > 60000 and (claim.rijdbaar or "").lower().startswith("nee"):
        out.append(_sig("V06_hoge_waarde_niet_rijdbaar", "Duur voertuig niet rijdbaar", f"Catalogusprijs € {cat:,}".replace(",", "."), "Voertuig"))

    # Tegenpartij ook bij RDW toetsen
    tp = claim.tegenpartij_kenteken
    if tp:
        try:
            trec = ctx.rdw.lookup(tp)
            if trec is None:
                out.append(_sig("V01_kenteken_onbekend_rdw", "Kenteken tegenpartij bestaat niet bij de RDW",
                                f"'{format_plate(tp)}' geeft geen resultaat.", "Voertuig", hard=True))
            elif (trec.get("wam_verzekerd", "").lower() == "nee"):
                out.append(_sig("V02_geen_wam_rdw", "Tegenpartij niet WAM verzekerd volgens RDW", format_plate(tp), "Voertuig"))
        except Exception as exc:
            ctx.checks.append(CheckResult("RDW tegenpartij", "fout", str(exc)))
    return out


# --------------------------------------------------------------------------- relatie
def rule_relatie(claim: Claim, ctx: RuleContext) -> list[Signal]:
    out = []
    naam = (claim.verzekerde or "").strip()
    if len(re.findall(r"\w+", naam)) < 2 and not re.search(r"\b(b\.?v\.?|v\.?o\.?f\.?|holding|groep|transport|taxi)\b", naam.lower()):
        out.append(_sig("R01_verzekerde_onvolledig", "Naam verzekerde is onvolledig", f"Alleen '{naam}' opgegeven.", "Relatie"))
    em = (claim.melder_email or "").lower()
    if em.endswith(FREEMAIL) or any(f in em for f in FREEMAIL):
        if claim.melder_bedrijf:
            out.append(_sig("R04_melder_freemail_zakelijk", "Zakelijke melder met privé mailadres", em, "Relatie"))
    return out


# --------------------------------------------------------------------------- dekking
def rule_dekking(claim: Claim, ctx: RuleContext) -> list[Signal]:
    """Stond het voertuig in de dekkingsbestanden (Carglass, ANWB) of in de BDX? Dat bevestigt dat het bij ons verzekerd is."""
    out = []
    # Alleen schades uit de BDX tellen. eFNOL meldingen (waaronder deze case zelf) bewijzen geen dekking.
    in_bdx = bool(ctx.history and any(r.bron != "eFNOL" and r.folder_id != claim.folder_id
                                      for r in ctx.history.as_insured_vehicle(claim.kenteken)))
    if not (ctx.coverage and ctx.coverage.available):
        ctx.checks.append(CheckResult("Dekkingsbestand", "niet beschikbaar", "Niet gecontroleerd of het voertuig in de dekkingsbestanden staat."))
        return out
    info = ctx.coverage.get(claim.kenteken)
    sd = claim.schadedatum
    if info is None:
        ctx.checks.append(CheckResult("Dekkingsbestand", "niet beschikbaar", "Kenteken is niet opgezocht in de dekkingsbestanden."))
        return out
    if info.geen_bestand_voor_schade and not info.voor_schade:
        ctx.checks.append(CheckResult("Dekkingsbestand", "niet beschikbaar",
                                      "Op de schadedatum bestonden nog geen dekkingsbestanden in de mailbox. Dekking handmatig controleren in LoxxoTech Admin."
                                      + (" Het voertuig staat wel in latere dekkingsbestanden." if info.na_schade else "")))
        return out
    if info.voor_schade:
        if info.eerst_gezien and sd and 0 <= (sd - info.eerst_gezien).days <= 14:
            out.append(_sig("V09_kort_voor_schade_in_dekkingsbestand", "Voertuig kort voor de schade aan de dekking toegevoegd",
                            f"Voor het eerst in een dekkingsbestand op {info.eerst_gezien:%d-%m-%Y}, {(sd - info.eerst_gezien).days} dagen voor de schade.", "Voertuig"))
        ctx.checks.append(CheckResult("Dekkingsbestand", "ok", "Voertuig stond voor de schadedatum in het dekkingsbestand"
                                      + (f" (eerst gezien {info.eerst_gezien:%d-%m-%Y})" if info.eerst_gezien else "") + "."))
    elif info.na_schade:
        out.append(_sig("V08_pas_na_schade_in_dekkingsbestand", "Voertuig pas na de schadedatum in het dekkingsbestand",
                        f"Eerst gezien {info.eerst_gezien:%d-%m-%Y}." if info.eerst_gezien else "Niet in dekkingsbestanden van voor de schade.",
                        "Voertuig", hard=True))
    elif in_bdx:
        ctx.checks.append(CheckResult("Dekkingsbestand", "ok", "Niet in de dekkingsbestanden gevonden maar wel bekend uit eerdere schades in de BDX."))
    else:
        out.append(_sig("V07_niet_in_dekkingsbestand", "Voertuig staat niet in het dekkingsbestand",
                        "Het kenteken komt niet voor in de dekkingsbestanden naar Carglass en ANWB en ook niet in de BDX. Controleer of het voertuig bij ons verzekerd is.",
                        "Voertuig"))
    return out


# --------------------------------------------------------------------------- signalen uit de stukken
HARDE_EXTRA = {"S01_rol_tegenstrijdig_met_pv", "S02_alcohol_of_drugs", "S08_foto_ander_voertuig"}


def rule_extra(claim: Claim, ctx: RuleContext) -> list[Signal]:
    """Signalen die bij het lezen van proces-verbaal, brieven of formulier zijn gevonden. Gewicht komt uit WEIGHTS."""
    out = []
    for e in claim.extra_signalen:
        code = e.get("code", "")
        if code not in WEIGHTS:
            continue
        out.append(Signal(code=code, titel=e.get("titel", code), toelichting=e.get("toelichting", ""),
                          gewicht=WEIGHTS[code], categorie=e.get("categorie", "Stukken"), hard=code in HARDE_EXTRA))
    return out


RULES: list[Callable[[Claim, RuleContext], list[Signal]]] = [
    rule_tijdlijn, rule_polis, rule_historie, rule_toedracht, rule_documentatie, rule_voertuig, rule_dekking, rule_relatie, rule_extra,
]
