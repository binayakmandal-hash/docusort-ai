"""Run the personal-number finder over every training document and record what it flags.

    python src/evaluate_sensitive.py

There is no labelled dataset of Indian personal numbers (for good reason), so this is a false-alarm
check: the training documents come from US, UK and Malaysian sources, so Aadhaar, PAN and IFSC hits
there would almost certainly be false alarms. Every hit was also read by hand; the rules for card,
Aadhaar and phone numbers were tightened after that review, so these counts are not a held-out test.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import sensitive  # noqa: E402


def main():
    docs = pd.read_csv(ROOT / "data" / "documents.csv")
    counts, with_hits = collections.Counter(), collections.Counter()
    for text in docs["text"]:
        kinds = [h["kind"] for h in sensitive.find(text)]
        counts.update(kinds)
        with_hits.update(set(kinds))
    result = {"documents": len(docs), "hits": dict(counts), "documents_with_hits": dict(with_hits)}
    print(json.dumps(result, indent=2))
    path = ROOT / "reports" / "metrics.json"
    m = json.loads(path.read_text())
    m["sensitive_scan"] = result
    path.write_text(json.dumps(m, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
