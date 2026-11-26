"""Dossieranalyse: samenvatting en eerste beoordeling van een schade voor de behandelaar.

De inhoudelijke analyse (toedracht, kruisjes en schets op het aanrijdingsformulier, aansprakelijkheid) komt
uit een JSON bestand dat Claude opstelt na het lezen van de melding, het formulier en de foto's.
Deze module controleert dat bestand, vult afgeleide velden aan (prioriteit, ontbrekende stukken) en maakt
er een rapport van in dezelfde Loxxo opmaak als de fraude-indicatie.

Zie DOSSIER_VOORBEELD voor de velden.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .report import (EASY, EXPERT, FONT, LABEL_BG, LINE, MUTED, NIVEAU_KLEUR, NOBORDER, PASSION, _cell, _e, _h2,
                     _logo_data_uri)

PRIORITEIT_KLEUR = {"Spoed": (PASSION, "#FFE3E4"), "Hoog": ("#9A5B00", "#FFF1D6"), "Normaal": ("#1E7B4F", "#E3F4EA")}

DOSSIER_VOORBEELD = {
    "kenteken": "Z-383-HL",
    "verzekerde": "naam",
    "samenvatting": "Korte samenvatting in 3 tot 5 zinnen.",
    "feiten": {"Datum en tijd": "", "Locatie": "", "Situatie": ""},
    "partijen": [
        {"rol": "A (verzekerde)", "bestuurder": "", "voertuig": "", "kenteken": "", "verzekeraar": "", "schade": ""},
        {"rol": "B (tegenpartij)", "bestuurder": "", "voertuig": "", "kenteken": "", "verzekeraar": "", "schade": ""},
    ],
    "formulier": {
        "aanwezig": True, "door_beide_getekend": True, "gewonden_aangekruist": False,
        "kruisjes_a": ["1 stond stil"], "kruisjes_b": ["8 botste op achterzijde"],
        "getuigen": "geen", "politie": "", "schets": "", "opmerkingen": "",
    },
    "beoordeling": {
        "aansprakelijkheid": "Tegenpartij", "aansprakelijkheid_pct_tegenpartij": 100,
        "onderbouwing": "", "voorrang": "", "letsel": False, "letsel_toelichting": "",
        "zwaarte": "Licht", "rijdbaar": True,
    },
    "reservering": {"totaal": 1500, "posten": [{"post": "Eigen schade (casco)", "bedrag": 1500, "toelichting": ""}],
                    "verhaal": "Volledig verhaalbaar op tegenpartij"},
    "aandachtspunten": ["..."],
    "vervolgstappen": ["..."],
    "ontbrekend": ["..."],
    "fraude_indicatie": {"niveau": "Laag", "score": 14, "link": ""},
}


def bepaal_prioriteit(d: dict) -> tuple[str, str]:
    """Spoed bij letsel, Hoog bij niet rijdbaar of zware schade, anders Normaal."""
    b = d.get("beoordeling", {})
    f = d.get("formulier", {})
    if b.get("letsel") or f.get("gewonden_aangekruist"):
        if (b.get("letsel_partij") or "").lower() == "eigen bestuurder":
            return "Hoog", ("Letsel bij de eigen bestuurder. Binnen 2 werkdagen contact opnemen en nagaan of er een "
                            "SVI of inzittendendekking op de polis zit.")
        return "Spoed", "Er is (mogelijk) letsel bij een derde. Binnen 24 uur contact opnemen en het letselschade traject starten."
    if b.get("rijdbaar") is False or (b.get("zwaarte") or "").lower() == "zwaar":
        return "Hoog", "Voertuig niet rijdbaar of zware schade. Binnen 2 werkdagen expertise en vervangend vervoer regelen."
    fraude = (d.get("fraude_indicatie") or {}).get("niveau")
    if fraude in ("Verhoogd", "Hoog"):
        return "Hoog", f"Fraude-indicatie {fraude}. Eerst de vragen uit het fraude rapport uitzetten."
    return "Normaal", "Geen letsel en voertuig rijdbaar. Reguliere behandeling binnen de normale termijn."


def euro(v) -> str:
    if v is None:
        return "Nog te bepalen"
    try:
        return "€ " + f"{float(v):,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v or "onbekend")


def render_dossier_html(d: dict, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    prio, prio_uitleg = bepaal_prioriteit(d)
    fg, bg = PRIORITEIT_KLEUR[prio]
    b = d.get("beoordeling", {})
    f = d.get("formulier", {})
    r = d.get("reservering", {})
    logo = _logo_data_uri()
    logo_html = (f"<img src='{logo}' width='130' height='36' alt='Loxxo'>" if logo
                 else f"<span style='font-size:24px;font-weight:bold;color:{EXPERT}'>Loxxo</span>")
    th = f"padding:7px 10px;border:1px solid {EXPERT};background:{EXPERT};color:#FFFFFF;font-weight:bold;text-align:left"

    def kv_table(rows: list[tuple[str, str]]) -> str:
        return "<table style='width:100%;border-collapse:collapse;font-size:12px'>" + "".join(
            "<tr>" + _cell(_e(k), f"background:{LABEL_BG};color:{MUTED}", width="30%") + _cell(_e(v), width="70%") + "</tr>"
            for k, v in rows if v not in (None, "")) + "</table>"

    def bullets(items, ordered=False) -> str:
        tag = "ol" if ordered else "ul"
        return f"<{tag} style='margin:0;padding-left:20px'>" + "".join(
            f"<li style='margin-bottom:5px'>{_e(x)}</li>" for x in items) + f"</{tag}>"

    # Kernpunten in één oogopslag
    pct = b.get("aansprakelijkheid_pct_tegenpartij")
    if r.get("totaal") is None and not r.get("posten"):
        r = dict(r, posten=[{"post": "Nog te bepalen", "bedrag": None, "toelichting": r.get("toelichting", "")}])
    aanspr = b.get("aansprakelijkheid", "onbekend") + (f" ({pct}% tegenpartij)" if pct is not None else "")
    kern = [
        ("Aansprakelijkheid", aanspr),
        ("Letsel", {True: "Ja. ", False: "Nee. "}.get(b.get("letsel"), "Onbekend. ") + (b.get("letsel_toelichting") or "")),
        ("Zwaarte", f"{b.get('zwaarte', 'onbekend')}. Rijdbaar: {'ja' if b.get('rijdbaar') else 'nee' if b.get('rijdbaar') is False else 'onbekend'}"),
        ("Reservering", f"{euro(r.get('totaal'))}. {r.get('verhaal', '')}".strip()),
    ]
    fr = d.get("fraude_indicatie") or {}
    if fr:
        kern.append(("Fraude-indicatie", f"{fr.get('niveau', '')} (score {fr.get('score', '?')})"))
    kern_table = "<table style='width:100%;border-collapse:collapse;font-size:13px'>" + "".join(
        "<tr>" + _cell(f"<b>{_e(k)}</b>", f"background:{LABEL_BG};color:{EXPERT}", width="30%") + _cell(_e(v), width="70%") + "</tr>"
        for k, v in kern) + "</table>"

    # Partijen naast elkaar
    partijen = d.get("partijen", [])
    velden = [("Bestuurder", "bestuurder"), ("Voertuig", "voertuig"), ("Kenteken", "kenteken"),
              ("Verzekeraar", "verzekeraar"), ("Schade", "schade")]
    w = f"{int(70 / max(1, len(partijen)))}%"
    partij_table = ("<table style='width:100%;border-collapse:collapse;font-size:12px'><tr>"
                    f"<td width='30%' style='{th}'>&nbsp;</td>"
                    + "".join(f"<td width='{w}' style='{th}'>{_e(p.get('rol', ''))}</td>" for p in partijen) + "</tr>"
                    + "".join("<tr>" + _cell(_e(lbl), f"background:{LABEL_BG};color:{MUTED}", width="30%")
                              + "".join(_cell(_e(p.get(key, "")), width=w) for p in partijen) + "</tr>" for lbl, key in velden)
                    + "</table>")

    form_rows = [
        ("Aanrijdingsformulier", "Aanwezig" + (", door beide partijen getekend" if f.get("door_beide_getekend") else ", niet door beide getekend")
         if f.get("aanwezig") else "Niet aanwezig"),
        ("Gewonden (vak 3)", ("Ja aangekruist" if f.get("gewonden_aangekruist") else "Nee aangekruist")
         if f.get("aanwezig") else "Niet bekend, geen formulier"),
        ("Toedracht A (vak 12)", "; ".join(f.get("kruisjes_a", []))),
        ("Toedracht B (vak 12)", "; ".join(f.get("kruisjes_b", []))),
        ("Getuigen", f.get("getuigen", "")), ("Politie", f.get("politie", "")),
        ("Situatieschets", f.get("schets", "")), ("Opmerkingen", f.get("opmerkingen", "")),
    ]
    feiten_rows = list((d.get("feiten") or {}).items())

    reserve_table = ""
    if r.get("posten"):
        reserve_table = ("<table style='width:100%;border-collapse:collapse;font-size:12px'>"
                         f"<tr><td width='30%' style='{th}'>Post</td><td width='52%' style='{th}'>Toelichting</td>"
                         f"<td width='18%' style='{th};text-align:right;white-space:nowrap'>Bedrag</td></tr>"
                         + "".join("<tr>" + _cell(_e(p.get("post", "")), width="30%") + _cell(_e(p.get("toelichting", "")), width="52%")
                                   + _cell(euro(p.get("bedrag")), "text-align:right;white-space:nowrap", width="18%") + "</tr>"
                                   for p in r["posten"])
                         + "<tr>" + _cell("<b>Totaal</b>", width="30%") + _cell(_e(r.get("verhaal", "")), width="52%")
                         + _cell(f"<b>{euro(r.get('totaal'))}</b>", "text-align:right;white-space:nowrap", width="18%") + "</tr></table>")

    plate = d.get("kenteken", "")
    fraude_link = (f" <a href='{_e(fr['link'])}' style='color:{EXPERT}'>Open de fraude-indicatie</a>" if fr.get("link") else "")

    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>Dossieranalyse {now:%Y-%m-%d} {_e(plate)}</title></head>
<body style="{FONT};color:#1B2533;font-size:13px;max-width:760px;margin:0 auto;padding:16px;background:#FFFFFF">

<table style="width:100%;border-collapse:collapse"><tr>
<td width="50%" style="{NOBORDER};padding:0 0 10px 0;vertical-align:middle;text-align:left">{logo_html}</td>
<td width="50%" style="{NOBORDER};padding:0 0 10px 0;vertical-align:middle;text-align:right;color:{MUTED};font-size:12px">
Dossieranalyse schademelding<br><b style="color:{EXPERT};font-size:15px">{_e(plate)}</b><br>{now:%d-%m-%Y %H:%M}</td>
</tr></table>
<table style="width:100%;border-collapse:collapse"><tr><td style="border:1px solid {PASSION};background:{PASSION};padding:0;font-size:2px;line-height:3px">&nbsp;</td></tr></table>

<table style="width:100%;border-collapse:collapse;margin-top:18px"><tr>
<td style="border:1px solid {bg};border-left:6px solid {fg};background:{bg};padding:14px 18px;text-align:left">
<span style="font-size:12px;color:{MUTED}">Prioriteit</span><br>
<span style="font-size:22px;font-weight:bold;color:{fg};white-space:nowrap">{_e(prio)}</span><br>
<span style="font-size:13px;color:#1B2533">{_e(prio_uitleg)}</span></td></tr></table>

{_h2("Samenvatting")}
<p style="margin:0">{_e(d.get("samenvatting", ""))}</p>

{_h2("Eerste beoordeling")}
{kern_table}
<p style="font-size:12px;color:#1B2533;margin:8px 0 0 0"><b>Onderbouwing aansprakelijkheid.</b> {_e(b.get("onderbouwing", ""))}</p>
{f'<p style="font-size:12px;color:#1B2533;margin:6px 0 0 0"><b>Voorrang.</b> {_e(b.get("voorrang"))}</p>' if b.get("voorrang") else ""}

{_h2("Volgende stappen voor de behandelaar")}
{bullets(d.get("vervolgstappen", []), ordered=True)}

{_h2("Aandachtspunten")}
{bullets(d.get("aandachtspunten", []))}

{_h2("Reservering (eerste inschatting)")}
{reserve_table}

{_h2("Feiten")}
{kv_table(feiten_rows)}

{_h2("Betrokken partijen")}
{partij_table}

{_h2("Aanrijdingsformulier")}
{kv_table(form_rows)}

{_h2("Nog op te vragen")}
{bullets(d.get("ontbrekend", []) or ["Niets. Het dossier is compleet voor een eerste beoordeling."])}

<p style="font-size:11px;color:{MUTED};margin-top:26px">
Deze analyse is automatisch opgesteld op basis van de melding, het aanrijdingsformulier en de foto's in de casemap.
Het is een eerste inschatting om de behandeling te versnellen. De behandelaar beoordeelt aansprakelijkheid,
dekking en reservering definitief.{fraude_link}</p>
</body></html>"""
