"""Measure receipt field extraction against SROIE's own answer key.

    python src/evaluate_fields.py --sources path/to/cloned/repos [--split dev|heldout]

SROIE (ICDAR 2019) gives, for each of 626 scanned receipts, the OCR text lines and the correct
seller name, date and total. The extraction rules in fields.py were written while looking only at
receipts 000-099 ("dev"); receipts 100-625 ("heldout") were not looked at, and that is the number
we report. Matching is exact after normalising spaces and case; for the seller name we also report
a looser match (one contains the other), because receipts often print the name twice in slightly
different forms.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fields  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_date(s: str | None) -> str:
    """Compare dates as day, month and two-digit year, so 25/12/2018 equals 25-12-18."""
    if not s:
        return ""
    m = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s.strip())
    if m:
        return f"{int(m.group(1)):02d}{int(m.group(2)):02d}{m.group(3)[-2:]}"
    return norm(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, type=Path)
    ap.add_argument("--split", choices=["dev", "heldout", "all"], default="heldout")
    ap.add_argument("--show", type=int, default=0, help="print this many misses per field")
    args = ap.parse_args()
    base = args.sources / "ICDAR-2019-SROIE" / "data"
    boxes = sorted((base / "box").glob("*.csv"))
    keep = {"dev": lambda i: i < 100, "heldout": lambda i: i >= 100, "all": lambda i: True}[args.split]
    stats = {"seller_exact": 0, "seller_loose": 0, "date": 0, "total": 0, "date_found": 0, "total_found": 0, "n": 0}
    misses = {"seller": [], "date": [], "total": []}
    for f in boxes:
        idx = int(f.stem)
        if not keep(idx):
            continue
        key_file = base / "key" / f"{f.stem}.json"
        if not key_file.exists():
            continue
        key = json.loads(key_file.read_text(encoding="utf-8", errors="ignore"))
        text = "\n".join(row.split(",", 8)[8] for row in f.read_text(encoding="utf-8", errors="ignore").splitlines() if row.count(",") >= 8)
        got = {x["name"]: x["value"] for x in fields.receipt_fields(text)}
        stats["n"] += 1
        s, k = norm(got["Seller"]), norm(key.get("company"))
        stats["seller_exact"] += s == k
        stats["seller_loose"] += bool(s and k and (s in k or k in s))
        if s != k:
            misses["seller"].append((f.stem, got["Seller"], key.get("company")))
        stats["date_found"] += bool(got["Date"])
        ok = norm_date(got["Date"]) == norm_date(key.get("date"))
        stats["date"] += ok
        if not ok:
            misses["date"].append((f.stem, got["Date"], key.get("date")))
        stats["total_found"] += bool(got["Total"])
        try:
            ok = got["Total"] is not None and abs(float(got["Total"]) - float(re.sub(r"[^\d.]", "", key.get("total", "")) or "nan")) < 0.005
        except ValueError:
            ok = False
        stats["total"] += ok
        if not ok:
            misses["total"].append((f.stem, got["Total"], key.get("total")))
    n = stats["n"]
    result = {"split": args.split, "receipts": n,
              "seller_exact": round(stats["seller_exact"] / n, 3), "seller_loose": round(stats["seller_loose"] / n, 3),
              "date": round(stats["date"] / n, 3), "total": round(stats["total"] / n, 3),
              "date_found": round(stats["date_found"] / n, 3), "total_found": round(stats["total_found"] / n, 3)}
    print(json.dumps(result, indent=2))
    for field, rows in misses.items():
        for r in rows[:args.show]:
            print(f"  miss {field:<6} {r[0]}: got {r[1]!r} expected {r[2]!r}")
    if args.split == "heldout":
        path = ROOT / "reports" / "metrics.json"
        m = json.loads(path.read_text()) if path.exists() else {}
        m["receipt_fields"] = result
        path.write_text(json.dumps(m, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
