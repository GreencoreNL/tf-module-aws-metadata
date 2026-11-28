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

    sec = "padding:22px 28px 0 28px"
    label = f"font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED};font-weight:bold;padding-bottom:8px"
    feiten = [("Verzekerde", c.verzekerde or "onbekend"), ("Kenteken", plate or "onbekend"), ("Schadedatum", sd)]
    rows_feit = "".join(
        f"<tr><td style='padding:6px 0;color:{MUTED};width:120px;border-top:1px solid #E6EAF0'>{k}</td>"
        f"<td style='padding:6px 0;font-weight:bold;border-top:1px solid #E6EAF0'>{_e(v)}</td></tr>" for k, v in feiten)
    rows_sig = "".join(
        f"<tr><td style='padding:9px 0;border-top:1px solid #E6EAF0'><div style='font-weight:bold'>{_e(x.titel)}</div>"
        f"<div style='color:{MUTED};font-size:13px;padding-top:2px'>{_e(x.toelichting)}</div></td></tr>" for x in top)
    rows_act = "".join(
        f"<tr><td style='padding:6px 10px 6px 0;vertical-align:top;width:22px'>"
        f"<div style='width:20px;height:20px;line-height:20px;border-radius:10px;background:{EXPERT};color:#fff;font-size:11px;"
        f"font-weight:bold;text-align:center'>{i}</div></td><td style='padding:6px 0;vertical-align:top'>{_e(x)}</td></tr>"
        for i, x in enumerate(acties, 1))
    # Het logo komt als inline bijlage mee. In Gmail: attachments[0] met inline=true, dan werkt cid:att0.
    html_body = f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F3F5F8;border-collapse:collapse"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#FFFFFF;border:1px solid #E6EAF0;border-collapse:collapse;{FONT};font-size:14px;line-height:1.45;color:#1B2533">
<tr><td style="padding:20px 28px 16px 28px;border-bottom:3px solid {PASSION}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>
<td style="vertical-align:middle"><img src="cid:att0" width="92" height="25" alt="Loxxo" style="display:block;border:0"></td>
<td style="vertical-align:middle;text-align:right;font-size:12px;color:{MUTED}">Fraude-indicatie</td></tr></table></td></tr>
<tr><td style="{sec}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{bg};border-radius:6px"><tr>
<td style="padding:14px 18px"><div style="font-size:18px;font-weight:bold;color:{fg}">{_e(a.niveau)}</div>
<div style="font-size:13px;color:{fg}">{kleur.capitalize()} signaal, score {a.score} van 100</div></td></tr></table></td></tr>
<tr><td style="{sec}"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows_feit}</table></td></tr>
<tr><td style="{sec}"><div style="{label}">Zwaarste signalen</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows_sig}</table></td></tr>
<tr><td style="{sec}"><div style="{label}">Eerst doen</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows_act}</table></td></tr>
<tr><td style="padding:22px 28px 24px 28px">
<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>
<td style="background:{EXPERT};border-radius:4px"><a href="{{RAPPORT_URL}}" style="display:inline-block;padding:10px 18px;color:#FFFFFF;font-weight:bold;text-decoration:none">Open rapport</a></td>
<td style="width:10px"></td>
<td style="border:1px solid {EXPERT};border-radius:4px"><a href="{{MAP_URL}}" style="display:inline-block;padding:9px 17px;color:{EXPERT};font-weight:bold;text-decoration:none">Open casemap</a></td>
</tr></table></td></tr>
<tr><td style="padding:14px 28px;background:#F8FAFC;border-top:1px solid #E6EAF0;font-size:12px;color:{MUTED}">Een signaal is een aanwijzing en geen bewijs. Neem geen besluit over dekking of uitkering op basis van alleen deze score.</td></tr>
</table></td></tr></table>"""
    text = "\n".join([
        f"Fraude-indicatie {a.niveau}, score {a.score} van 100", "",
        f"Verzekerde: {c.verzekerde or 'onbekend'}", f"Kenteken: {plate or 'onbekend'}", f"Schadedatum: {sd}", "",
        "Zwaarste signalen", *[f"  {x.titel}: {x.toelichting}" for x in top], "",
        "Eerst doen", *[f"  {i}. {x}" for i, x in enumerate(acties, 1)], "",
        "Rapport: {RAPPORT_URL}", "Casemap: {MAP_URL}", "",
        "Een signaal is een aanwijzing en geen bewijs.",
    ])
    return {"subject": subject, "html": html_body, "text": text}
