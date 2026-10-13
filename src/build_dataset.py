"""Build the DocuSort training set from public datasets of real documents.

Each class comes from a public, real-world source (see DATASETS.md for licences and links):

    receipt_invoice   ICDAR 2019 SROIE scanned receipts (OCR text)
    contract          CUAD v1, 510 commercial contracts filed with the SEC
    resume            resume_corpus (florex), resumes from indeed.com
    email             Enron email corpus (non-spam messages)
    news_article      BBC News dataset (2,225 articles)
    scientific_paper  SciTLDR full text (computer-science papers from OpenReview) and
                      PubMed 20k RCT abstracts (medical research), half from each
    form              FUNSD, 199 scanned forms (OCR text from the annotations)
    medical_report    MTSamples medical transcriptions

Usage:
    python src/build_dataset.py --sources path/to/cloned/repos --out data/documents.csv

The source repos are cloned with `git clone --depth 1` (see README). Each class is capped at
600 documents (fixed seed) so no class dominates, and each document is cut to its first
6,000 characters, which is also what the app reads.

Because every class above comes from a single source, a model can partly learn "which dataset is
this from" instead of "what kind of document is this". So the script also writes an OUTSIDE test
set (--outside) from different sources that are never used for training:

    receipt_invoice   invoice2data sample invoices (PDF, real vendors)
    news_article      AG News articles

A first model trained with SciTLDR as the only source of scientific papers labelled 7.5% of PubMed
abstracts correctly (it called them medical reports): it had learned "computer-science topic",
not "research paper". That's why PubMed's training split is now part of the training data, and
evaluate.py repeats that leave-one-source-out experiment for the record.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import subprocess
import zipfile
from pathlib import Path

CAP = 600
MAX_CHARS = 6000
SEED = 42
TAG = re.compile(r"<[^>]+>")


def clip(text: str) -> str:
    text = TAG.sub(" ", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def sroie(src: Path):
    for f in sorted((src / "ICDAR-2019-SROIE" / "data" / "box").glob("*.csv")):
        lines = []
        for row in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = row.split(",", 8)
            if len(parts) == 9:
                lines.append(parts[8])
        yield "receipt_invoice", "\n".join(lines), f"sroie/{f.stem}"


def invoices(src: Path):
    for f in sorted((src / "invoice2data").rglob("*.pdf")):
        try:
            out = subprocess.run(["pdftotext", "-layout", str(f), "-"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        yield "receipt_invoice", out, f"invoice2data/{f.stem}"


def cuad(src: Path):
    with zipfile.ZipFile(src / "cuad" / "data.zip") as z:
        data = json.load(z.open("CUADv1.json"))["data"]
    for d in data:
        yield "contract", d["paragraphs"][0]["context"], f"cuad/{d['title'][:60]}"


def resumes(src: Path):
    with zipfile.ZipFile(src / "resume_corpus" / "resumes_corpus.zip") as z:
        names = sorted(n for n in z.namelist() if n.endswith(".txt"))
        for n in random.Random(SEED).sample(names, min(len(names), CAP * 3)):
            yield "resume", z.read(n).decode("utf-8", errors="ignore"), f"resume_corpus/{Path(n).stem}"


def enron(src: Path):
    import pandas as pd
    with zipfile.ZipFile(src / "enron_spam_data" / "enron_spam_data.zip") as z:
        df = pd.read_csv(z.open("enron_spam_data.csv"))
    df = df[df["Spam/Ham"] == "ham"].dropna(subset=["Message"])
    for _, r in df.sample(n=min(len(df), CAP * 3), random_state=SEED).iterrows():
        yield "email", f"Subject: {r['Subject']}\n{r['Message']}", f"enron/{r['Message ID']}"


def bbc(src: Path):
    import pandas as pd
    df = pd.read_csv(src / "BBC-Dataset-News-Classification" / "dataset" / "dataset.csv", encoding="latin-1")
    for i, r in df.iterrows():
        yield "news_article", r["news"], f"bbc/{r['type']}/{i}"


def scitldr(src: Path):
    base = src / "scitldr" / "SciTLDR-Data" / "SciTLDR-FullText"
    for split in ("train", "dev", "test"):
        for line in (base / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            yield "scientific_paper", " ".join(d["source"]), f"scitldr/{d.get('paper_id', '')}"


def funsd(src: Path):
    with zipfile.ZipFile(src / "FUNSD" / "dataset.zip") as z:
        for n in sorted(n for n in z.namelist() if n.endswith(".json") and "MACOSX" not in n):
            form = json.load(z.open(n))["form"]
            form.sort(key=lambda f: (round(f["box"][1] / 12), f["box"][0]))  # reading order: rows, then left to right
            yield "form", "\n".join(f["text"] for f in form if f["text"].strip()), f"funsd/{Path(n).stem}"


def mtsamples(src: Path):
    import pandas as pd
    df = pd.read_csv(src / "medical-nlp" / "data" / "mtsamples.csv").dropna(subset=["transcription"])
    for i, r in df.iterrows():
        yield "medical_report", r["transcription"], f"mtsamples/{i}"


def agnews(src: Path):
    rows = list(csv.reader(open(src / "CharCnn_Keras" / "data" / "ag_news_csv" / "test.csv", encoding="utf-8")))
    for i, (_, title, body) in enumerate(random.Random(SEED).sample(rows, 120)):
        yield "news_article", f"{title}\n{body.replace(chr(92), ' ')}", f"agnews/{i}"


def _pubmed(src: Path, split: str, n: int):
    text = (src / "pubmed-rct" / "PubMed_20k_RCT" / f"{split}.txt").read_text(encoding="utf-8")
    abstracts = [a for a in text.split("\n\n") if a.strip()]
    for a in random.Random(SEED).sample(abstracts, n):
        lines = a.strip().splitlines()
        body = " ".join(l.split("\t", 1)[1] for l in lines[1:] if "\t" in l)
        yield "scientific_paper", body, f"pubmed/{lines[0].lstrip('#')}"


def pubmed_train(src: Path):
    yield from _pubmed(src, "train", CAP)


READERS = [sroie, cuad, resumes, enron, bbc, scitldr, pubmed_train, funsd, mtsamples]
OUTSIDE = [invoices, agnews]


def build(src: Path, readers=None) -> list[dict]:
    by_label: dict[str, list[dict]] = {}
    seen = set()
    for reader in readers or READERS:
        for label, text, doc_id in reader(src):
            text = clip(text)
            key = re.sub(r"\W+", "", text.lower())[:400]
            if len(text.split()) < 15 or key in seen:  # too short to be a document, or a duplicate
                continue
            seen.add(key)
            by_label.setdefault(label, []).append({"label": label, "source": doc_id.split("/")[0], "doc_id": doc_id, "text": text})
    rows = []
    rng = random.Random(SEED)
    for label, docs in sorted(by_label.items()):
        rng.shuffle(docs)
        # Take documents from each source in turn, so a class with two sources is split evenly.
        by_source: dict[str, list[dict]] = {}
        for d in docs:
            by_source.setdefault(d["source"], []).append(d)
        queues = list(by_source.values())
        picked = []
        while len(picked) < CAP and any(queues):
            for q in queues:
                if q and len(picked) < CAP:
                    picked.append(q.pop())
        rows += picked
    return rows


def write(rows: list[dict], out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["label", "source", "doc_id", "text"])
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[(r["label"], r["source"])] = counts.get((r["label"], r["source"]), 0) + 1
    print(f"Wrote {len(rows)} documents to {out}")
    for (label, source), v in sorted(counts.items()):
        print(f"  {label:<18} {source:<14} {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, type=Path)
    ap.add_argument("--out", default=Path("data/documents.csv"), type=Path)
    ap.add_argument("--outside", default=Path("data/outside_test.csv"), type=Path)
    args = ap.parse_args()
    write(build(args.sources), args.out)
    write(build(args.sources, OUTSIDE), args.outside)


if __name__ == "__main__":
    main()
