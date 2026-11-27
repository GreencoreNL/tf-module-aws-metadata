"""Schademeldingen die per mail in claims@loxxo.nl binnenkomen omzetten naar een casemap.

De melding wordt geschreven in hetzelfde formaat als de eFNOL melding uit de Fleet Portal. Daardoor werken
fraudecheck en dossieranalyse zonder aanpassing. De melding en de originele mail gaan als PDF in de map, met de bijlagen ernaast. Er komt geen HTML in de map.

Welke mails een nieuwe schademelding zijn bepaalt de run zelf (zie README). Deze module bouwt alleen de bestanden.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import format_plate

ROW = ("<tr><td style=\"padding:6px 10px;width:35%;vertical-align:top;color:#555;border-bottom:1px solid #e3e6ec\">{k}</td>"
       "<td style=\"padding:6px 10px;vertical-align:top;border-bottom:1px solid #e3e6ec\">{v}</td></tr>")
HEAD = "<tr><th colspan=\"2\" style=\"background:#1f3864;color:#fff;text-align:left;padding:8px 10px\">{t}</th></tr>"


def _safe(name: str) -> str:
    return " ".join(re.sub(r"[\\\\/:*?\"<>|]+", " ", name).split())


def is_test(m: dict) -> bool:
    """Testmelding: melder met een loxxo.nl adres of TEST in verzekerde of referentie."""
    mail = (m.get("melder_email") or "").lower()
    return mail.endswith("@loxxo.nl") or any("TEST" in (m.get(k) or "").upper() for k in ("verzekerde", "referentie"))


def melddatum(m: dict) -> datetime:
    """De dag dat de melding bij Loxxo binnenkwam, in Amsterdamse tijd. Bij een doorgestuurde mail via info@
    is dat de datum van de originele mail (veld 'ontvangen_origineel'). Nooit de schadedatum."""
    d: datetime = m.get("ontvangen_origineel") or m["ontvangen"]
    if d.tzinfo is not None:
        from zoneinfo import ZoneInfo
        d = d.astimezone(ZoneInfo("Europe/Amsterdam")).replace(tzinfo=None)
    return d


def folder_name(m: dict) -> str:
    """'Melddatum Kenteken Verzekerde', met TEST vooraan bij een testmelding."""
    naam = f"{melddatum(m):%Y-%m-%d} {format_plate(m.get('kenteken', '')) or 'onbekend kenteken'} {m.get('verzekerde', '')}"
    return _safe(("TEST " if is_test(m) else "") + naam)[:120]


def mail_file_name(m: dict, afzender_naam: str) -> str:
    """'Mail Melddatum Afzender Kenmerk Kenteken.pdf', bijvoorbeeld 'Mail 2026-11-26 Allianz 672CC2044DN FN-R7-7D.pdf'."""
    delen = [f"{melddatum(m):%Y-%m-%d}", afzender_naam, m.get("kenmerk", ""), format_plate(m.get("kenteken", ""))]
    return _safe("Mail " + " ".join(d for d in delen if d))[:150] + ".pdf"


def melding_html(m: dict) -> str:
    """m: verzekerde, kenteken, schadedatum (dd-mm-jjjj), tijdstip, wat_gebeurd, tegenpartij, kenteken_tegenpartij,
    rijdbaar, toedracht, melder_naam, melder_bedrijf, melder_email, melder_telefoon, referentie, ontvangen (datetime),
    onderwerp, message_id, bijlagen (lijst namen)."""
    e = lambda v: html.escape(str(v or ""))  # noqa: E731
    ontv = melddatum(m)
    schade = [("Verzekerde", m.get("verzekerde")), ("Kenteken", format_plate(m.get("kenteken")) or m.get("kenteken")),
              ("Schadedatum", m.get("schadedatum")), ("Tijdstip", m.get("tijdstip")), ("Wat is er gebeurd", m.get("wat_gebeurd")),
              ("Plaats", m.get("plaats")), ("Bestuurder", m.get("bestuurder")), ("Tegenpartij", m.get("tegenpartij")),
              ("Kenteken tegenpartij", m.get("kenteken_tegenpartij")), ("Letsel", m.get("letsel")), ("Rijdbaar", m.get("rijdbaar")),
              ("Toedracht", m.get("toedracht"))]
    melder = [("Naam", m.get("melder_naam")), ("Bedrijf", m.get("melder_bedrijf")), ("E-mail", m.get("melder_email")),
              ("Telefoon", m.get("melder_telefoon")), ("Referentie melder", m.get("referentie"))]
    bron = [("Bron", "E-mail aan claims@loxxo.nl"), ("Onderwerp", m.get("onderwerp")), ("Ontvangen", f"{ontv:%d-%m-%Y %H:%M}"),
            ("Gmail bericht", m.get("message_id"))]
    rows = lambda items: "".join(ROW.format(k=e(k), v=e(v)) for k, v in items if v not in (None, ""))  # noqa: E731
    bijlagen = m.get("bijlagen") or []
    return (
        "<!doctype html><html lang='nl'><head><meta charset='utf-8'></head><body>"
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;max-width:680px\">"
        f"<p>Beste,</p><p>Hierbij een nieuwe schademelding voor <b>{e(m.get('verzekerde'))}</b> met kenteken "
        f"<b>{e(format_plate(m.get('kenteken')))}</b>. De melding is op {ontv:%d-%m-%Y} om {ontv:%H:%M} bij Loxxo binnengekomen.</p>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Schade')}{rows(schade)}</table>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Melder')}{rows(melder)}</table>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Bron')}{rows(bron)}</table>"
        + (f"<p>In de bijlage: {e(', '.join(bijlagen))}.</p>" if bijlagen else "<p>Er zijn bij deze melding geen bestanden meegestuurd.</p>")
        + "</div></body></html>"
    )


def mail_html(mail: dict) -> str:
    """Kopie van de originele mail. mail: van, aan, cc, datum (datetime), onderwerp, bijlagen (namen),
    tekst (platte tekst) of html (de HTML body uit Gmail). De HTML body heeft voorrang zodat opmaak en tabellen blijven."""
    e = html.escape
    d: datetime = mail["datum"]
    kop = [("Van", mail.get("van")), ("Aan", mail.get("aan")), ("Cc", mail.get("cc")),
           ("Datum", f"{d:%d-%m-%Y %H:%M}"), ("Onderwerp", mail.get("onderwerp")),
           ("Bijlagen", ", ".join(mail.get("bijlagen") or []) or "Geen")]
    kop_html = "".join(f"<tr><td style='padding:2px 10px 2px 0;color:#555;vertical-align:top;white-space:nowrap'><b>{k}</b></td>"
                       f"<td style='padding:2px 0'>{e(str(v))}</td></tr>" for k, v in kop if v)
    if mail.get("html"):
        body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", mail["html"])
        body = re.sub(r"(?is)</?(html|head|body|meta)[^>]*>", "", body)
    else:
        body = f"<div style='white-space:pre-wrap'>{e(mail.get('tekst') or '')}</div>"
    return (f"<!doctype html><html lang='nl'><head><meta charset='utf-8'><title>{e(mail.get('onderwerp') or '')}</title>"
            "<style>body{font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#222} img{max-width:100%}"
            "table{max-width:100%}</style></head><body>"
            f"<table style='border-collapse:collapse;margin-bottom:8px'>{kop_html}</table>"
            f"<hr style='border:0;border-top:1px solid #999;margin:8px 0 12px'>{body}</body></html>")


def _chrome() -> str:
    import os
    import shutil
    for c in (os.environ.get("CHROME_BIN"), "/opt/pw-browsers/chromium", "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise RuntimeError("Geen Chrome of Chromium gevonden. Zet CHROME_BIN.")


def html_to_pdf(html_text: str, path: Path) -> Path:
    """Zet HTML om naar een A4 PDF met headless Chrome. Er wordt niets van internet geladen."""
    import subprocess
    import tempfile

    page_css = "<style>@page{size:A4;margin:15mm}</style>"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.html"
        src.write_text(page_css + html_text, encoding="utf-8")
        subprocess.run([_chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={tmp}/profiel",
                        f"--print-to-pdf={path}", src.as_uri()], check=True, capture_output=True, timeout=120)
    if not Path(path).exists():
        raise RuntimeError(f"PDF niet gemaakt: {path}")
    return Path(path)


def write_case(base: Path, m: dict, mail: dict, afzender_naam: str,
               attachments: Optional[dict[str, Path]] = None) -> Path:
    """Maakt lokaal een casemap met de melding (PDF), de originele mail (PDF) en de bijlagen. Geen HTML in de map."""
    import shutil

    m = dict(m)
    m.setdefault("bijlagen", list(attachments or {}))
    folder = base / folder_name(m)
    folder.mkdir(parents=True, exist_ok=True)
    html_to_pdf(melding_html(m), folder / f"Melding {folder.name}.pdf")
    mail = dict(mail)
    mail.setdefault("bijlagen", list(attachments or {}))
    html_to_pdf(mail_html(mail), folder / mail_file_name(m, afzender_naam))
    for name, src in (attachments or {}).items():
        shutil.copy(src, folder / _safe(name))
    return folder
