"""Zet signalen om in een score van 0 tot 100 en een niveau met vervolgacties."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Assessment, Claim, Signal
from .rules import RULES, RuleContext

DREMPEL_VERHOOGD = 25
DREMPEL_HOOG = 50

ACTIES = {
    "T01_schadedatum_na_melding": "Bel de melder en laat de juiste schadedatum bevestigen. Leg vast of het een invoerfout is.",
    "T02_nachtelijk_tijdstip": "Vraag naar de reden van de rit en wie er reed.",
    "T03_late_melding_30": "Vraag waarom de schade zo laat is gemeld.",
    "T03_late_melding_14": "Vraag waarom de schade niet direct is gemeld.",
    "T04_kort_na_polisingang_30": "Vraag de voorverzekering en schadevrije jaren op. Toets of de schade al bestond bij aanvang.",
    "T05_kort_na_toevoegen_voertuig": "Controleer de aankoop en de staat van het voertuig bij toevoegen.",
    "T06_na_einde_dekking": "Toets dekking. Niet uitkeren voordat vaststaat dat er op schadedatum dekking was.",
    "T07_recent_tenaamgesteld": "Vraag koopcontract en foto's van het voertuig bij aankoop.",
    "T09_datum_formulier_wijkt_af": "Leg de datum op het formulier naast de melding en vraag om uitleg.",
    "H01_kenteken_eerder_schade_2plus": "Vergelijk schadebeeld met eerdere schades op dit kenteken (zelfde plek, zelfde reparateur).",
    "H02_kenteken_als_tegenpartij": "Bekijk de eerdere dossiers waarin dit voertuig tegenpartij was.",
    "H03_tegenpartij_vaker_betrokken": "Bekijk de eerdere dossiers van de tegenpartij. Overweeg melding bij de fraudecoördinator.",
    "H04_fraude_register": "Neem contact op met de fraudecoördinator voordat er iets wordt toegezegd of uitgekeerd.",
    "H05_eerder_fraudevlag": "Lees het eerdere fraudedossier voordat je de schade behandelt.",
    "H06_contactgegevens_bij_andere_verzekerden": "Ga na hoe de melder verbonden is met de andere verzekerden.",
    "H07_zelfde_partijen_eerder": "Draag over aan de fraudecoördinator. Herhaalde aanrijding tussen dezelfde voertuigen.",
    "D01_toedracht_te_kort": "Vraag een volledige toedracht met plaats, rijrichting, snelheid en situatieschets.",
    "D04_kop_staart_zonder_details": "Vraag naar locatie, verkeerssituatie en getuigen.",
    "A01_geen_fotos": "Vraag foto's van de schade en van het hele voertuig met kenteken in beeld.",
    "A02_geen_formulier_bij_tegenpartij": "Vraag het ingevulde en door beide partijen getekende aanrijdingsformulier op.",
    "A03_foto_ouder_dan_schade": "Vraag originele foto's met metadata. Mogelijk een eerdere schade.",
    "A05_tegenpartij_kenteken_onbekend": "Vraag het kenteken van de tegenpartij op.",
    "V01_kenteken_onbekend_rdw": "Controleer het kenteken met de melder en de polis.",
    "V02_geen_wam_rdw": "Controleer de verzekeringsstatus bij RDW en polis.",
    "V04_export": "Ga na of het voertuig nog in Nederland is. Niet uitkeren zonder inspectie.",
    "R01_verzekerde_onvolledig": "Laat de volledige naam van de verzekerde en het polisnummer bevestigen.",
    "R02_verzekerde_onbekend_crm": "Koppel de melding aan het juiste wagenpark en polis.",
}


def niveau_voor(score: int, hard: bool) -> str:
    if score >= DREMPEL_HOOG:
        return "Hoog"
    if score >= DREMPEL_VERHOOGD or hard:
        return "Verhoogd"
    return "Laag"


def assess(claim: Claim, ctx: RuleContext, now: Optional[datetime] = None) -> Assessment:
    signals: list[Signal] = []
    for rule in RULES:
        signals.extend(rule(claim, ctx))
    # Een code telt maar één keer mee in de score (hoogste gewicht wint)
    seen: dict[str, int] = {}
    for s in signals:
        seen[s.code] = max(seen.get(s.code, 0), s.gewicht)
    score = min(100, sum(seen.values()))
    hard = any(s.hard for s in signals)
    signals.sort(key=lambda s: (-int(s.hard), -s.gewicht))
    acties = []
    for s in signals:
        a = ACTIES.get(s.code)
        if a and a not in acties:
            acties.append(a)
    niveau = niveau_voor(score, hard)
    if niveau == "Laag" and not acties:
        acties.append("Geen bijzondere acties. Normale behandeling.")
    return Assessment(claim=claim, score=score, niveau=niveau, signals=signals, checks=ctx.checks,
                      vervolgacties=acties, gegenereerd_op=now or datetime.now())
