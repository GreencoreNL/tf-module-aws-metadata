"""Schademeldingen die per mail in claims@loxxo.nl binnenkomen omzetten naar een casemap.

De melding wordt geschreven in hetzelfde formaat als de eFNOL melding uit de Fleet Portal. Daardoor werken
fraudecheck en dossieranalyse zonder aanpassing. De originele mail gaat als apart bestand mee in de map.

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
    return re.sub(r"[\\\\/:*?\"<>|]+", " ", name).strip()


def folder_name(ontvangen: datetime, kenteken: str, verzekerde: str) -> str:
    return _safe(f"{ontvangen:%Y-%m-%d} {format_plate(kenteken) or 'onbekend kenteken'} {verzekerde} (mail)")[:120]


def melding_html(m: dict) -> str:
    """m: verzekerde, kenteken, schadedatum (dd-mm-jjjj), tijdstip, wat_gebeurd, tegenpartij, kenteken_tegenpartij,
    rijdbaar, toedracht, melder_naam, melder_bedrijf, melder_email, melder_telefoon, referentie, ontvangen (datetime),
    onderwerp, message_id, bijlagen (lijst namen)."""
    e = lambda v: html.escape(str(v or ""))  # noqa: E731
    ontv: datetime = m["ontvangen"]
    schade = [("Verzekerde", m.get("verzekerde")), ("Kenteken", m.get("kenteken")), ("Schadedatum", m.get("schadedatum")),
              ("Tijdstip", m.get("tijdstip")), ("Wat is er gebeurd", m.get("wat_gebeurd")), ("Tegenpartij", m.get("tegenpartij")),
              ("Kenteken tegenpartij", m.get("kenteken_tegenpartij")), ("Rijdbaar", m.get("rijdbaar")), ("Toedracht", m.get("toedracht"))]
    melder = [("Naam", m.get("melder_naam")), ("Bedrijf", m.get("melder_bedrijf")), ("E-mail", m.get("melder_email")),
              ("Telefoon", m.get("melder_telefoon")), ("Referentie melder", m.get("referentie"))]
    bron = [("Bron", "E-mail aan claims@loxxo.nl"), ("Onderwerp", m.get("onderwerp")), ("Ontvangen", f"{ontv:%d-%m-%Y %H:%M}"),
            ("Gmail bericht", m.get("message_id"))]
    rows = lambda items: "".join(ROW.format(k=e(k), v=e(v)) for k, v in items if v not in (None, ""))  # noqa: E731
    bijlagen = m.get("bijlagen") or []
    return (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;max-width:680px\">"
        f"<p>Beste,</p><p>Hierbij een nieuwe schademelding voor <b>{e(m.get('verzekerde'))}</b> met kenteken "
        f"<b>{e(m.get('kenteken'))}</b>. De melding is op {ontv:%d-%m-%Y} om {ontv:%H:%M} bij Loxxo binnengekomen.</p>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Schade')}{rows(schade)}</table>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Melder')}{rows(melder)}</table>"
        f"<table style=\"border-collapse:collapse;width:100%;margin:14px 0\">{HEAD.format(t='Bron')}{rows(bron)}</table>"
        + (f"<p>In de bijlage: {e(', '.join(bijlagen))}.</p>" if bijlagen else "<p>Er zijn bij deze melding geen bestanden meegestuurd.</p>")
        + "</div>"
    )


def mail_html(afzender: str, aan: str, datum: datetime, onderwerp: str, tekst: str) -> str:
    """Leesbare kopie van de originele mail voor in de casemap."""
    e = html.escape
    return (f"<!doctype html><html lang='nl'><head><meta charset='utf-8'><title>{e(onderwerp)}</title></head>"
            f"<body style='font-family:Arial,sans-serif;font-size:13px;max-width:760px'>"
            f"<p><b>Van:</b> {e(afzender)}<br><b>Aan:</b> {e(aan)}<br><b>Datum:</b> {datum:%d-%m-%Y %H:%M}<br>"
            f"<b>Onderwerp:</b> {e(onderwerp)}</p><hr><pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>{e(tekst)}</pre>"
            f"</body></html>")


def write_case(base: Path, m: dict, mail_text: str, afzender: str, aan: str,
               attachments: Optional[dict[str, Path]] = None) -> Path:
    """Maakt lokaal een casemap met melding, originele mail en bijlagen. Geeft het pad terug."""
    import shutil

    folder = base / folder_name(m["ontvangen"], m.get("kenteken", ""), m.get("verzekerde", ""))
    folder.mkdir(parents=True, exist_ok=True)
    ontv: datetime = m["ontvangen"]
    stem = _safe(f"{ontv:%Y-%m-%d} {format_plate(m.get('kenteken', ''))} {m.get('verzekerde', '')}")
    (folder / f"Melding {stem}.html").write_text(melding_html(m), encoding="utf-8")
    (folder / f"Mail {ontv:%Y-%m-%d} {_safe(m.get('onderwerp', ''))[:80]}.html").write_text(
        mail_html(afzender, aan, ontv, m.get("onderwerp", ""), mail_text), encoding="utf-8")
    for name, src in (attachments or {}).items():
        shutil.copy(src, folder / _safe(name))
    return folder
