"""Command line.

  python -m fraudcheck drive  --root <folderId> [--bdx-sheet ID] [--fraud-file ID ...] [--policies polis.json] [--dry-run] [--force]
  python -m fraudcheck local  <casemap> [<casemap> ...] [--bdx bdx.csv] [--fraud fraud.xlsx] [--out rapporten/]

'local' werkt op mappen op schijf met dezelfde inhoud als de Drive casemappen (handig voor testen).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

from .models import Attachment
from .parse_form import parse_form_text
from .parse_melding import parse_melding_html
from .pipeline import build_history, exif_datetime, run
import json

from .report import MAIL_NIVEAUS, render_email, render_html, report_title, to_json
from .rules import RuleContext
from .scoring import assess
from .sources.context import CoverageLookup, PolicyLookup
from .sources.history import ClaimRecord, HistoryIndex, bdx_rows_to_records, fraud_rows_to_records, read_csv, read_xlsx
from .sources.rdw import RDWClient

DEFAULT_ROOT = "1Hruq_Gr9JsMY2gZ8iVhKhpob96FdR7Nv"        # 0.3.6.30 Schademeldingen documenten
DEFAULT_BDX = "12T-8wR2Yk1lW08wTecuCtsidjra8A-kuZRwTUuoVZQg"  # Project BDX 2.0
DEFAULT_FRAUD = ["1A5EDFjv0y4LcsjQekIheWfKjmpksZJ0u", "1YgIgOb6sCC7WCstljtclS4FUvsJXx6ll", "1QAR9TlQxImp0qLlCn9qry1EDU2KkIg-m"]


def _load_local_case(path: Path):
    melding = next((p for p in path.iterdir() if p.name.lower().startswith("melding") and p.suffix == ".html"), None)
    if not melding:
        return None
    claim = parse_melding_html(melding.read_text(encoding="utf-8"), folder_id=str(path), folder_name=path.name)
    for p in path.iterdir():
        if p == melding or p.name.startswith(("Fraude-indicatie", "Dossieranalyse", "Mail ")):
            continue
        if p.suffix == ".txt" and p.stem.endswith(".ocr"):
            continue
        if p.name == "signalen.json":
            claim.extra_signalen = json.loads(p.read_text(encoding="utf-8"))
            continue
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else ("application/pdf" if p.suffix.lower() == ".pdf" else "")
        att = Attachment(name=p.name, mime_type=mime, local_path=str(p))
        if att.is_photo:
            att.exif_datetime = exif_datetime(p.read_bytes())
        ocr = p.with_name(p.name + ".ocr.txt")
        if ocr.exists():
            att.text = ocr.read_text(encoding="utf-8")
            claim.form_fields[att.name] = parse_form_text(att.text)
        claim.attachments.append(att)
    return claim


def cmd_local(args):
    cases = [c for c in (_load_local_case(Path(p)) for p in args.cases) if c]
    idx = HistoryIndex()
    if args.bdx:
        rows = read_csv(args.bdx) if args.bdx.endswith(".csv") else read_xlsx(args.bdx, header_contains="Vehicle Registration Index")
        idx.add_claims(bdx_rows_to_records(rows), "BDX")
    for f in args.fraud or []:
        idx.add_fraud(fraud_rows_to_records(read_xlsx(f, header_contains="Vehicle Reg")), Path(f).stem)
    idx.add_claims([ClaimRecord(bron="eFNOL", referentie=c.folder_name, kenteken=c.plate, tegenpartij_kenteken=c.tegenpartij_kenteken,
                                schadedatum=c.schadedatum, verzekerde=c.verzekerde, folder_id=c.folder_id) for c in cases], "eFNOL meldingen")
    policies = PolicyLookup.from_json(args.policies) if args.policies else None
    coverage = CoverageLookup.from_json(args.coverage) if args.coverage else None
    rdw = None if args.no_rdw else RDWClient()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for c in cases:
        ctx = RuleContext(history=idx, rdw=rdw, policies=policies, coverage=coverage, today=date.today())
        a = assess(c, ctx)
        name = report_title(a)
        (out / f"{name}.html").write_text(render_html(a), encoding="utf-8")
        (out / f"{name}.json").write_text(to_json(a), encoding="utf-8")
        if a.niveau in MAIL_NIVEAUS:
            (out / f"{name}.mail.json").write_text(json.dumps(render_email(a), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{a.niveau:9} {a.score:3}  {c.folder_name}")


def cmd_drive(args):
    from .drive import Drive

    drive = Drive(args.credentials)
    policies = PolicyLookup.from_json(args.policies) if args.policies else None
    results = run(drive, args.root, rdw=RDWClient(), policies=policies, bdx_sheet=args.bdx_sheet,
                  fraud_files=args.fraud_file, force=args.force, dry_run=args.dry_run)
    for a in results:
        print(f"{a.niveau:9} {a.score:3}  {a.claim.folder_name}")


def cmd_dossier(args):
    from .dossier import render_dossier_html

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    for f in args.analyses:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        name = f"Dossieranalyse {now:%Y-%m-%d} {d.get('kenteken', Path(f).stem)}"
        (out / f"{name}.html").write_text(render_dossier_html(d, now), encoding="utf-8")
        print(name)


def cmd_intake(args):
    """Maakt casemappen van schademeldingen per mail. Invoer: JSON met melding, mailtekst en bijlagen (zie README)."""
    from .intake import write_case

    for f in args.mails:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        m = dict(d["melding"])
        m["ontvangen"] = datetime.fromisoformat(m["ontvangen"])
        att = {k: Path(v) for k, v in (d.get("bijlagen") or {}).items()}
        m.setdefault("bijlagen", list(att))
        folder = write_case(Path(args.out), m, d.get("mailtekst", ""), d.get("afzender", ""), d.get("aan", ""), att)
        print(folder)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="fraudcheck")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("drive", help="Beoordeel nieuwe cases in Google Drive")
    d.add_argument("--root", default=os.environ.get("FRAUDCHECK_ROOT", DEFAULT_ROOT))
    d.add_argument("--credentials", default=None)
    d.add_argument("--bdx-sheet", default=os.environ.get("FRAUDCHECK_BDX", DEFAULT_BDX))
    d.add_argument("--fraud-file", action="append", default=None)
    d.add_argument("--policies", default=os.environ.get("FRAUDCHECK_POLICIES"))
    d.add_argument("--force", action="store_true", help="Ook cases met een bestaand rapport opnieuw beoordelen")
    d.add_argument("--dry-run", action="store_true", help="Niets wegschrijven")
    d.set_defaults(func=cmd_drive)

    l = sub.add_parser("local", help="Beoordeel casemappen op schijf")
    l.add_argument("cases", nargs="+")
    l.add_argument("--bdx")
    l.add_argument("--fraud", action="append")
    l.add_argument("--policies")
    l.add_argument("--coverage", help="JSON per kenteken: staat het in de dekkingsbestanden (zie README)")
    l.add_argument("--no-rdw", action="store_true")
    l.add_argument("--out", default="rapporten")
    l.set_defaults(func=cmd_local)

    ds = sub.add_parser("dossier", help="Maak een dossieranalyse rapport van een analyse JSON")
    ds.add_argument("analyses", nargs="+")
    ds.add_argument("--out", default="rapporten")
    ds.set_defaults(func=cmd_dossier)

    it = sub.add_parser("intake", help="Maak casemappen van schademeldingen uit de claims@ mailbox")
    it.add_argument("mails", nargs="+")
    it.add_argument("--out", default="cases")
    it.set_defaults(func=cmd_intake)

    args = ap.parse_args(argv)
    if args.cmd == "drive" and args.fraud_file is None:
        args.fraud_file = DEFAULT_FRAUD
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
