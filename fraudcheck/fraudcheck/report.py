"""Rapport per case in de Loxxo huisstijl.

Inline styles en tabellen zodat het rapport ook goed blijft als Drive het omzet naar een Google Doc.
Kleuren: Expert Blue #002E5D, Easy Blue #CAE2FF, Passion Red #FF5055. Lettertype Work Sans.
"""
from __future__ import annotations

import html
import json
from dataclasses import asdict

from .models import Assessment, format_plate

EXPERT = "#002E5D"
EASY = "#CAE2FF"
PASSION = "#FF5055"
NIVEAU_KLEUR = {"Laag": ("#1E7B4F", "#E3F4EA"), "Verhoogd": ("#9A5B00", "#FFF1D6"), "Hoog": (PASSION, "#FFE3E4")}
FONT = "font-family:'Work Sans',Arial,Helvetica,sans-serif"


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def report_title(a: Assessment) -> str:
    c = a.claim
    return f"Fraude-indicatie {a.gegenereerd_op:%Y-%m-%d} {format_plate(c.kenteken)} {a.niveau}"


def render_html(a: Assessment) -> str:
    c = a.claim
    fg, bg = NIVEAU_KLEUR[a.niveau]
    rows_signals = "".join(
        f"<tr><td style='padding:8px 10px;border-bottom:1px solid #E3E6EC;vertical-align:top;width:34%'>"
        f"<b>{_e(s.titel)}</b>{' <span style=\"color:' + PASSION + ';font-weight:bold\">rode vlag</span>' if s.hard else ''}<br>"
        f"<span style='color:#5A6B80;font-size:12px'>{_e(s.categorie)} · {_e(s.code.split('_')[0])}</span></td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #E3E6EC;vertical-align:top'>{_e(s.toelichting)}</td>"
        f"<td style='padding:8px 10px;border-bottom:1px solid #E3E6EC;vertical-align:top;text-align:right;width:40px'>+{s.gewicht}</td></tr>"
        for s in a.signals
    ) or "<tr><td style='padding:8px 10px' colspan='3'>Geen signalen gevonden.</td></tr>"

    rows_checks = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #E3E6EC;width:34%'>{_e(k.bron)}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #E3E6EC;width:110px;color:{'#1E7B4F' if k.status == 'ok' else ('#9A5B00' if k.status == 'niet beschikbaar' else PASSION)}'>{_e(k.status)}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #E3E6EC'>{_e(k.detail)}</td></tr>"
        for k in a.checks
    )
    acties = "".join(f"<li style='margin-bottom:4px'>{_e(x)}</li>" for x in a.vervolgacties)

    gegevens = [
        ("Verzekerde", c.verzekerde), ("Kenteken", format_plate(c.kenteken)),
        ("Schadedatum", c.schadedatum.strftime("%d-%m-%Y") if c.schadedatum else "onbekend"),
        ("Tijdstip", c.schadetijd or "niet opgegeven"),
        ("Gemeld op", c.gemeld_op.strftime("%d-%m-%Y %H:%M") if c.gemeld_op else "onbekend"),
        ("Wat is er gebeurd", c.wat_gebeurd), ("Toedracht", c.toedracht), ("Tegenpartij", c.tegenpartij),
        ("Kenteken tegenpartij", format_plate(c.tegenpartij_kenteken) or "onbekend"),
        ("Melder", " · ".join(dict.fromkeys(x for x in (c.melder_naam, c.melder_bedrijf) if x))),
        ("Bijlagen", ", ".join(x.name for x in c.attachments) or "geen"),
    ]
    rows_gegevens = "".join(
        f"<tr><td style='padding:5px 10px;color:#5A6B80;width:34%;border-bottom:1px solid #E3E6EC'>{_e(k)}</td>"
        f"<td style='padding:5px 10px;border-bottom:1px solid #E3E6EC'>{_e(v)}</td></tr>" for k, v in gegevens
    )

    sterkste = (a.signals[0].titel[0].lower() + a.signals[0].titel[1:]) if a.signals else "geen signalen"
    conclusie = {
        "Hoog": f"Behandel deze schade niet regulier. Eerst de vervolgacties hieronder uitvoeren. Zwaarste signaal: {sterkste}.",
        "Verhoogd": f"Behandel deze schade met extra aandacht en voer de vervolgacties uit voor toezegging of uitkering. Zwaarste signaal: {sterkste}.",
        "Laag": "Geen aanleiding voor extra onderzoek. Normale behandeling.",
    }[a.niveau]

    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>{_e(report_title(a))}</title></head>
<body style="{FONT};color:#1B2533;font-size:14px;max-width:760px;margin:0 auto;padding:16px;background:#FFFFFF">
<table style="width:100%;border-collapse:collapse;background:{EXPERT};color:#FFFFFF">
<tr><td style="padding:18px 20px"><span style="font-size:22px;font-weight:bold">Loxxo</span><br>
<span style="font-size:13px;color:{EASY}">Fraude-indicatie schademelding</span></td>
<td style="padding:18px 20px;text-align:right;font-size:13px;color:{EASY}">{_e(format_plate(c.kenteken))}<br>{a.gegenereerd_op:%d-%m-%Y %H:%M}</td></tr></table>

<table style="width:100%;border-collapse:collapse;margin:16px 0;background:{bg}">
<tr><td style="padding:16px 20px;width:150px;vertical-align:middle">
<span style="font-size:12px;color:#5A6B80">Indicatie</span><br>
<span style="font-size:26px;font-weight:bold;color:{fg}">{_e(a.niveau)}</span><br>
<span style="font-size:13px;color:{fg}">score {a.score} van 100</span></td>
<td style="padding:16px 20px;vertical-align:middle">{_e(conclusie)}</td></tr></table>

<h2 style="{FONT};color:{EXPERT};font-size:17px;margin:22px 0 6px">Vervolgacties</h2>
<ol style="margin:0;padding-left:20px">{acties}</ol>

<h2 style="{FONT};color:{EXPERT};font-size:17px;margin:22px 0 6px">Signalen ({len(a.signals)})</h2>
<table style="width:100%;border-collapse:collapse">{rows_signals}</table>

<h2 style="{FONT};color:{EXPERT};font-size:17px;margin:22px 0 6px">Gegevens uit de melding</h2>
<table style="width:100%;border-collapse:collapse">{rows_gegevens}</table>

<h2 style="{FONT};color:{EXPERT};font-size:17px;margin:22px 0 6px">Uitgevoerde controles</h2>
<table style="width:100%;border-collapse:collapse">{rows_checks}</table>

<p style="font-size:12px;color:#5A6B80;margin-top:24px;border-top:2px solid {EASY};padding-top:10px">
Deze indicatie is automatisch opgesteld op basis van de melding, de bijlagen en interne en openbare bronnen.
Een signaal is een aanwijzing en geen bewijs. Gebruik de indicatie om te bepalen welke vragen je stelt en
neem geen besluit over dekking of uitkering op basis van alleen deze score. Drempels: Verhoogd vanaf 25,
Hoog vanaf 50. Een rode vlag maakt een case altijd minimaal Verhoogd.</p>
</body></html>"""


def to_json(a: Assessment) -> str:
    def default(o):
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return str(o)
    d = asdict(a)
    d["claim"].pop("raw", None)
    for att in d["claim"].get("attachments", []):
        att.pop("text", None)
    return json.dumps(d, default=default, ensure_ascii=False, indent=2)


MAIL_NIVEAUS = ("Verhoogd", "Hoog")


def render_email(a: Assessment) -> dict:
    """Korte waarschuwingsmail voor claims@loxxo.nl bij Verhoogd of Hoog.

    De links zijn placeholders {RAPPORT_URL} en {MAP_URL}. Die vult de run in na het uploaden van het rapport.
    """
    c = a.claim
    fg, bg = NIVEAU_KLEUR[a.niveau]
    kleur = "rood" if a.niveau == "Hoog" else "oranje"
    plate = format_plate(c.kenteken)
    subject = f"Fraude-indicatie {a.niveau}: {plate} {c.verzekerde} (score {a.score})"
    top = a.signals[:3]
    acties = a.vervolgacties[:3]
    sd = c.schadedatum.strftime("%d-%m-%Y") if c.schadedatum else "onbekend"

    li_sig = "".join(f"<li style='margin-bottom:4px'><b>{_e(s.titel)}</b><br><span style='color:#5A6B80'>{_e(s.toelichting)}</span></li>" for s in top)
    li_act = "".join(f"<li style='margin-bottom:4px'>{_e(x)}</li>" for x in acties)
    html_body = f"""<div style="{FONT};font-size:14px;color:#1B2533;max-width:640px">
<table style="width:100%;border-collapse:collapse;background:{EXPERT};color:#FFFFFF"><tr>
<td style="padding:14px 18px"><b style="font-size:18px">Loxxo</b><br><span style="color:{EASY};font-size:13px">Fraude-indicatie schademelding</span></td></tr></table>
<p>Hoi team,</p>
<p>De fraudecheck geeft een <b style="color:{fg}">{kleur} signaal</b> voor de schade van <b>{_e(c.verzekerde)}</b> met kenteken <b>{_e(plate)}</b> (schadedatum {sd}).</p>
<table style="width:100%;border-collapse:collapse;background:{bg}"><tr><td style="padding:12px 16px">
<b style="font-size:20px;color:{fg}">{_e(a.niveau)}</b> <span style="color:{fg}">score {a.score} van 100</span></td></tr></table>
<p style="margin-bottom:4px"><b>Zwaarste signalen</b></p><ul style="margin-top:0;padding-left:20px">{li_sig}</ul>
<p style="margin-bottom:4px"><b>Eerst doen</b></p><ol style="margin-top:0;padding-left:20px">{li_act}</ol>
<p><a href="{{RAPPORT_URL}}" style="color:{EXPERT};font-weight:bold">Open het volledige rapport</a> · <a href="{{MAP_URL}}" style="color:{EXPERT}">Open de casemap</a></p>
<p style="font-size:12px;color:#5A6B80">Een signaal is een aanwijzing en geen bewijs. Neem geen besluit over dekking of uitkering op basis van alleen deze score.</p>
</div>"""
    text = "\n".join([
        "Hoi team,", "",
        f"De fraudecheck geeft een {kleur} signaal voor de schade van {c.verzekerde} met kenteken {plate} (schadedatum {sd}).",
        f"Indicatie {a.niveau}, score {a.score} van 100.", "", "Zwaarste signalen",
        *[f"  {s.titel}: {s.toelichting}" for s in top], "", "Eerst doen",
        *[f"  {i}. {x}" for i, x in enumerate(acties, 1)], "",
        "Rapport: {RAPPORT_URL}", "Casemap: {MAP_URL}", "",
        "Een signaal is een aanwijzing en geen bewijs.",
    ])
    return {"subject": subject, "html": html_body, "text": text}
