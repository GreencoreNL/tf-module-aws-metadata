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
from datetime import date
from pathlib import Path

from .models import Attachment
from .parse_form import parse_form_text
from .parse_melding import parse_melding_html
from .pipeline import build_history, exif_datetime, run
from .report import render_html, report_title, to_json
from .rules import RuleContext
from .scoring import assess
from .sources.context import PolicyLookup, customers_from_json, zoho_customer_lookup
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
        if p == melding or p.name.startswith("Fraude-indicatie"):
            continue
        if p.suffix == ".txt" and p.stem.endswith(".ocr"):
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
    customers = customers_from_json(args.customers) if args.customers else None
    rdw = None if args.no_rdw else RDWClient()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for c in cases:
        ctx = RuleContext(history=idx, rdw=rdw, policies=policies, customers=customers, today=date.today())
        a = assess(c, ctx)
        name = report_title(a)
        (out / f"{name}.html").write_text(render_html(a), encoding="utf-8")
        (out / f"{name}.json").write_text(to_json(a), encoding="utf-8")
        print(f"{a.niveau:9} {a.score:3}  {c.folder_name}")


def cmd_drive(args):
    from .drive import Drive

    drive = Drive(args.credentials)
    policies = PolicyLookup.from_json(args.policies) if args.policies else None
    customers = zoho_customer_lookup() if os.environ.get("ZOHO_REFRESH_TOKEN") else None
    results = run(drive, args.root, rdw=RDWClient(), policies=policies, customers=customers, bdx_sheet=args.bdx_sheet,
                  fraud_files=args.fraud_file, force=args.force, dry_run=args.dry_run)
    for a in results:
        print(f"{a.niveau:9} {a.score:3}  {a.claim.folder_name}")


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
    l.add_argument("--customers", help="JSON met verzekerden zoals in Zoho gevonden")
    l.add_argument("--no-rdw", action="store_true")
    l.add_argument("--out", default="rapporten")
    l.set_defaults(func=cmd_local)

    args = ap.parse_args(argv)
    if args.cmd == "drive" and args.fraud_file is None:
        args.fraud_file = DEFAULT_FRAUD
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
