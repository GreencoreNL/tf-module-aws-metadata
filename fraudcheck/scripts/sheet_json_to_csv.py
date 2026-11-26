"""Zet een opgeslagen Google Sheets get_values resultaat (JSON met 'values') om naar CSV.

  python scripts/sheet_json_to_csv.py <input.json> <output.csv>
"""
import csv
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
values = json.load(open(src, encoding="utf-8"))["values"]
hdr = values[0]
with open(dst, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(hdr)
    for row in values[1:]:
        w.writerow(row + [""] * (len(hdr) - len(row)))
print(f"{len(values) - 1} rijen naar {dst}")
