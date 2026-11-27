"""Loopt alle casemappen langs, beoordeelt nieuwe cases en zet het rapport in de casemap."""
from __future__ import annotations

import io
import logging
import tempfile
from datetime import date, datetime
from typing import Optional

from .models import Attachment, Claim
from .parse_form import parse_form_text
from .parse_melding import parse_melding_html, parse_melding_pdf
from .report import render_html, report_title
from .rules import RuleContext
from .scoring import assess
from .sources.history import ClaimRecord, HistoryIndex, bdx_rows_to_records, fraud_rows_to_records, read_xlsx

log = logging.getLogger("fraudcheck")
REPORT_PREFIX = "Fraude-indicatie"


def exif_datetime(data: bytes) -> Optional[datetime]:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        raw = exif.get(36867) or exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal of DateTime
        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S") if raw else None
    except Exception:
        return None


def load_case(drive, folder: dict, ocr: bool = True) -> Optional[Claim]:
    files = drive.list_children(folder["id"])
    meldingen = [f for f in files if f["name"].lower().startswith("melding") and f["name"].lower().endswith((".pdf", ".html"))]
    melding = min(meldingen, key=lambda f: not f["name"].lower().endswith(".pdf"), default=None)
    if not melding:
        log.warning("Geen melding in %s", folder["name"])
        return None
    data = drive.download(melding["id"])
    if melding["name"].lower().endswith(".pdf"):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(data)
            tmp.flush()
            claim = parse_melding_pdf(tmp.name, folder["id"], folder["name"])
    else:
        claim = parse_melding_html(data.decode("utf-8", errors="replace"), folder["id"], folder["name"])
    for f in files:
        if f["id"] == melding["id"] or f["name"].startswith(REPORT_PREFIX):
            continue
        att = Attachment(name=f["name"], mime_type=f["mimeType"], file_id=f["id"])
        if att.is_photo:
            att.exif_datetime = exif_datetime(drive.download(f["id"]))
        elif ocr and (f["mimeType"] == "application/pdf" or att.is_form):
            try:
                att.text = drive.ocr_text(f["id"], folder["id"])
                claim.form_fields[att.name] = parse_form_text(att.text)
            except Exception as exc:  # OCR is best effort
                log.warning("OCR mislukt voor %s: %s", f["name"], exc)
        claim.attachments.append(att)
    return claim


def build_history(drive, cases: list[Claim], bdx_sheet: Optional[str], bdx_range: str,
                  fraud_files: list[str]) -> HistoryIndex:
    idx = HistoryIndex()
    if bdx_sheet:
        rows = drive.sheet_rows(bdx_sheet, bdx_range)
        idx.add_claims(bdx_rows_to_records(rows), "BDX Van Ameyde")
    for fid in fraud_files:
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
            tmp.write(drive.download(fid))
            tmp.flush()
            rows = read_xlsx(tmp.name, header_contains="Vehicle Reg")
        idx.add_fraud(fraud_rows_to_records(rows), f"Fraude register {fid[:6]}")
    efnol = [ClaimRecord(bron="eFNOL", referentie=c.folder_name, kenteken=c.plate, tegenpartij_kenteken=c.tegenpartij_kenteken,
                         schadedatum=c.schadedatum, verzekerde=c.verzekerde, oorzaak=c.wat_gebeurd,
                         telefoon=_phone(c.melder_telefoon), email=(c.melder_email or "").lower(), folder_id=c.folder_id)
             for c in cases]
    idx.add_claims(efnol, "eFNOL meldingen")
    return idx


def _phone(v):
    from .models import normalize_phone
    return normalize_phone(v)


def run(drive, root_folder: str, *, rdw=None, policies=None, customers=None, bdx_sheet: Optional[str] = None,
        bdx_range: str = "'bdx 011225'!A1:BX", fraud_files: Optional[list[str]] = None, force: bool = False,
        dry_run: bool = False, ocr: bool = True) -> list:
    folders = drive.list_children(root_folder, folders_only=True)
    todo, cases = [], []
    for folder in folders:
        names = [f["name"] for f in drive.list_children(folder["id"])]
        done = any(n.startswith(REPORT_PREFIX) for n in names)
        claim = load_case(drive, folder, ocr=ocr and (force or not done))
        if not claim:
            continue
        cases.append(claim)
        if force or not done:
            todo.append(claim)
    log.info("%d cases gevonden, %d te beoordelen", len(cases), len(todo))
    if not todo:
        return []
    history = build_history(drive, cases, bdx_sheet, bdx_range, fraud_files or [])
    results = []
    for claim in todo:
        ctx = RuleContext(history=history, rdw=rdw, policies=policies, customers=customers, today=date.today())
        a = assess(claim, ctx)
        log.info("%s: %s (%d)", claim.folder_name, a.niveau, a.score)
        if not dry_run:
            drive.upload_html_as_doc(claim.folder_id, report_title(a), render_html(a))
        results.append(a)
    return results
