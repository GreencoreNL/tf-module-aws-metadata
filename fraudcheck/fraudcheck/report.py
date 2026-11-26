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
FONT = "font-family:Work Sans,Arial,sans-serif"


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def report_title(a: Assessment) -> str:
    c = a.claim
    return f"Fraude-indicatie {a.gegenereerd_op:%Y-%m-%d} {format_plate(c.kenteken)} {a.niveau}"


def _logo_data_uri() -> str:
    import base64
    from pathlib import Path

    path = Path(__file__).parent / "assets" / "loxxo-logo-expert-blue.png"
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""


LINE = "#E3E6EC"
MUTED = "#5A6B80"
LABEL_BG = "#F4F7FB"
NOBORDER = "border:1px solid #FFFFFF"


def _cell(content: str, style: str = "", width: str = "") -> str:
    w = f" width='{width}'" if width else ""
    return f"<td{w} style='padding:7px 10px;border:1px solid {LINE};vertical-align:top;text-align:left;{style}'>{content}</td>"


def _h2(text: str) -> str:
    return f"<h2 style=\"{FONT};color:{EXPERT};font-size:15px;font-weight:bold;margin:26px 0 8px\">{_e(text)}</h2>"


def render_html(a: Assessment) -> str:
    c = a.claim
    fg, bg = NIVEAU_KLEUR[a.niveau]
    plate = format_plate(c.kenteken)
    logo = _logo_data_uri()
    logo_html = (f"<img src='{logo}' width='130' height='36' alt='Loxxo'>" if logo
                 else f"<span style='font-size:24px;font-weight:bold;color:{EXPERT}'>Loxxo</span>")

    sterkste = (a.signals[0].titel[0].lower() + a.signals[0].titel[1:]) if a.signals else "geen signalen"
    conclusie = {
        "Hoog": f"Behandel deze schade niet regulier. Voer eerst de vervolgacties uit. Zwaarste signaal: {sterkste}.",
        "Verhoogd": f"Behandel deze schade met extra aandacht en voer de vervolgacties uit voor toezegging of uitkering. Zwaarste signaal: {sterkste}.",
        "Laag": "Geen aanleiding voor extra onderzoek. Normale behandeling.",
    }[a.niveau]

    th = f"padding:7px 10px;border:1px solid {EXPERT};background:{EXPERT};color:#FFFFFF;font-weight:bold;text-align:left"
    if a.signals:
        rows = "".join(
            "<tr>"
            + _cell(f"<b>{_e(s.titel)}</b>"
                    + (f"<br><span style='color:{PASSION};font-weight:bold;font-size:11px'>RODE VLAG</span>" if s.hard else "")
                    + f"<br><span style='color:{MUTED};font-size:11px'>{_e(s.categorie)}</span>", width="33%")
            + _cell(_e(s.toelichting), width="55%")
            + _cell(f"+{s.gewicht}", "text-align:right;white-space:nowrap", width="12%")
            + "</tr>"
            for s in a.signals)
        signal_table = (f"<table style='width:100%;border-collapse:collapse;font-size:12px'>"
                        f"<tr><td width='33%' style='{th}'>Signaal</td><td width='55%' style='{th}'>Toelichting</td>"
                        f"<td width='12%' style='{th};text-align:right;white-space:nowrap'>Punten</td></tr>{rows}</table>")
    else:
        signal_table = "<p>Geen signalen gevonden.</p>"

    gegevens = [
        ("Verzekerde", c.verzekerde), ("Kenteken", plate),
        ("Schadedatum", c.schadedatum.strftime("%d-%m-%Y") if c.schadedatum else "onbekend"),
        ("Tijdstip", c.schadetijd or "niet opgegeven"),
        ("Gemeld op", c.gemeld_op.strftime("%d-%m-%Y %H:%M") if c.gemeld_op else "onbekend"),
        ("Wat is er gebeurd", c.wat_gebeurd), ("Toedracht", c.toedracht), ("Tegenpartij", c.tegenpartij),
        ("Kenteken tegenpartij", format_plate(c.tegenpartij_kenteken) or "onbekend"),
        ("Melder", " · ".join(dict.fromkeys(x for x in (c.melder_naam, c.melder_bedrijf) if x))),
        ("Bijlagen", ", ".join(x.name for x in c.attachments) or "geen"),
    ]
    gegevens_table = "<table style='width:100%;border-collapse:collapse;font-size:12px'>" + "".join(
        "<tr>" + _cell(_e(k), f"background:{LABEL_BG};color:{MUTED}", width="30%") + _cell(_e(v), width="70%") + "</tr>"
        for k, v in gegevens) + "</table>"

    status_kleur = {"ok": "#1E7B4F", "niet beschikbaar": "#9A5B00"}
    checks_table = (f"<table style='width:100%;border-collapse:collapse;font-size:12px'>"
                    f"<tr><td width='27%' style='{th}'>Bron</td><td width='21%' style='{th}'>Status</td><td width='52%' style='{th}'>Toelichting</td></tr>"
                    + "".join("<tr>" + _cell(_e(k.bron), width="27%")
                              + _cell(_e(k.status), f"color:{status_kleur.get(k.status, PASSION)};font-weight:bold;white-space:nowrap", width="21%")
                              + _cell(_e(k.detail), width="52%") + "</tr>" for k in a.checks)
                    + "</table>")

    acties = "".join(f"<li style='margin-bottom:5px'>{_e(x)}</li>" for x in a.vervolgacties)

    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>{_e(report_title(a))}</title></head>
<body style="{FONT};color:#1B2533;font-size:13px;max-width:760px;margin:0 auto;padding:16px;background:#FFFFFF">

<table style="width:100%;border-collapse:collapse"><tr>
<td width="50%" style="{NOBORDER};padding:0 0 10px 0;vertical-align:middle;text-align:left">{logo_html}</td>
<td width="50%" style="{NOBORDER};padding:0 0 10px 0;vertical-align:middle;text-align:right;color:{MUTED};font-size:12px">
Fraude-indicatie schademelding<br><b style="color:{EXPERT};font-size:15px">{_e(plate)}</b><br>{a.gegenereerd_op:%d-%m-%Y %H:%M}</td>
</tr></table>
<table style="width:100%;border-collapse:collapse"><tr><td style="border:1px solid {PASSION};background:{PASSION};padding:0;font-size:2px;line-height:3px">&nbsp;</td></tr></table>

<table style="width:100%;border-collapse:collapse;margin-top:18px"><tr>
<td style="border:1px solid {bg};border-left:6px solid {fg};background:{bg};padding:14px 18px;text-align:left">
<span style="font-size:12px;color:{MUTED}">Indicatie</span><br>
<span style="font-size:22px;font-weight:bold;color:{fg};white-space:nowrap">{_e(a.niveau)}</span>
<span style="font-size:13px;color:{fg};white-space:nowrap">&nbsp;&nbsp;score {a.score} van 100</span><br>
<span style="font-size:13px;color:#1B2533">{_e(conclusie)}</span></td></tr></table>

{_h2("Vervolgacties")}
<ol style="margin:0;padding-left:20px">{acties}</ol>

{_h2(f"Signalen ({len(a.signals)})")}
{signal_table}

{_h2("Gegevens uit de melding")}
{gegevens_table}

{_h2("Uitgevoerde controles")}
{checks_table}

<p style="font-size:11px;color:{MUTED};margin-top:26px">
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
