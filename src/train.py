"""Train and evaluate the DocuSort document-type classifier.

    python src/train.py                 # train, evaluate, save models/docusort.joblib and reports/

Everything printed here is also written to reports/metrics.json, which the README and the app's
"How accurate is it?" page read from, so the numbers shown are always the measured ones.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import make_pipeline, make_union
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[1]
SEED = 42
LABELS = ["contract", "email", "form", "medical_report", "news_article", "receipt_invoice", "resume", "scientific_paper"]


def features():
    """Word and character n-grams. Characters help with OCR typos and with short, number-heavy text like receipts."""
    return make_union(
        TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2, max_features=150_000, strip_accents="unicode"),
        TfidfVectorizer(sublinear_tf=True, analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=150_000),
    )


def candidates():
    return {
        "Complement Naive Bayes (words)": make_pipeline(
            TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2), ComplementNB(alpha=0.1)),
        "Logistic regression (words + characters)": make_pipeline(features(), LogisticRegression(C=10, max_iter=3000)),
        "Linear SVM (words + characters)": make_pipeline(features(), LinearSVC(C=0.5)),
    }


def final_model():
    """Linear SVM with calibrated probabilities, so the app can show a confidence and say 'not sure'."""
    return make_pipeline(features(), CalibratedClassifierCV(LinearSVC(C=0.5), cv=5, method="sigmoid", ensemble=False))


def slim(model):
    """Drop the list of pruned n-grams that TfidfVectorizer keeps only for inspection; it is most of the file size."""
    for _, vec in model.steps[0][1].transformer_list:
        if hasattr(vec, "stop_words_"):
            vec.stop_words_ = None
    return model


def ocr_noise(text: str, rate: float, rng: random.Random) -> str:
    """Simulate OCR mistakes: swap look-alike characters, drop or duplicate characters."""
    swaps = {"o": "0", "0": "o", "l": "1", "1": "l", "i": "l", "e": "c", "s": "5", "5": "s", "b": "6", "m": "rn", "a": "o"}
    out = []
    for ch in text:
        r = rng.random()
        if r < rate / 3 and ch.lower() in swaps:
            out.append(swaps[ch.lower()])
        elif r < 2 * rate / 3:
            continue
        elif r < rate:
            out.append(ch + ch)
        else:
            out.append(ch)
    return "".join(out)


def per_class(y_true, y_pred):
    p, r, f, n = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    return {lab: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3), "f1": round(float(f[i]), 3), "support": int(n[i])}
            for i, lab in enumerate(LABELS)}


def main():
    t0 = time.time()
    data = pd.read_csv(ROOT / "data" / "documents.csv")
    outside = pd.read_csv(ROOT / "data" / "outside_test.csv")
    train, test = train_test_split(data, test_size=0.2, stratify=data["label"], random_state=SEED)
    report: dict = {"dataset": {"train": len(train), "test": len(test), "outside": len(outside),
                                "per_class": data["label"].value_counts().sort_index().to_dict(),
                                "sources": data.groupby("label")["source"].unique().apply(list).to_dict()}}

    # 1. Compare models with 5-fold cross-validation on the training split only.
    print("5-fold cross-validation (macro F1) on the training split:")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    report["cross_validation"] = {}
    for name, model in candidates().items():
        scores = cross_val_score(model, train["text"], train["label"], cv=cv, scoring="f1_macro", n_jobs=-1)
        report["cross_validation"][name] = {"mean": round(float(scores.mean()), 4), "std": round(float(scores.std()), 4)}
        print(f"  {name:<44} {scores.mean():.4f} ± {scores.std():.4f}")

    # 2. Final model on the held-out test split.
    model = final_model().fit(train["text"], train["label"])
    pred = model.predict(test["text"])
    report["test"] = {"accuracy": round(accuracy_score(test["label"], pred), 4),
                      "macro_f1": round(f1_score(test["label"], pred, average="macro"), 4),
                      "per_class": per_class(test["label"], pred),
                      "confusion": {"labels": LABELS, "matrix": confusion_matrix(test["label"], pred, labels=LABELS).tolist()}}
    print(f"\nHeld-out test ({len(test)} documents): accuracy {report['test']['accuracy']:.4f}, macro F1 {report['test']['macro_f1']:.4f}")

    # 3. Documents from sources never seen in training.
    opred = model.predict(outside["text"])
    report["outside"] = {"accuracy": round(accuracy_score(outside["label"], opred), 4), "by_source": {}}
    print(f"Outside sources ({len(outside)} documents): accuracy {report['outside']['accuracy']:.4f}")
    for src, grp in outside.groupby("source"):
        p = model.predict(grp["text"])
        report["outside"]["by_source"][src] = {"label": grp["label"].iloc[0], "n": len(grp),
                                               "accuracy": round(accuracy_score(grp["label"], p), 4),
                                               "predicted": pd.Series(p).value_counts().to_dict()}
        print(f"  {src:<14} {accuracy_score(grp['label'], p):.4f}  {pd.Series(p).value_counts().to_dict()}")

    # 4. Leave one source out: is "scientific paper" learned as a document type or as a topic?
    report["leave_one_source_out"] = {}
    print("Leave one source out (scientific_paper):")
    for held in ("pubmed", "scitldr"):
        tr = train[~((train["label"] == "scientific_paper") & (train["source"] == held))]
        te = data[(data["label"] == "scientific_paper") & (data["source"] == held)]
        p = make_pipeline(features(), LinearSVC(C=0.5)).fit(tr["text"], tr["label"]).predict(te["text"])
        report["leave_one_source_out"][held] = {"n": len(te), "accuracy": round(accuracy_score(te["label"], p), 4),
                                               "predicted": pd.Series(p).value_counts().to_dict()}
        print(f"  trained without {held:<8} {accuracy_score(te['label'], p):.4f}  {pd.Series(p).value_counts().head(3).to_dict()}")

    # 5. Robustness: a short snippet (like a photo of the top of a page) and simulated OCR errors.
    rng = random.Random(SEED)
    report["robustness"] = {}
    for name, texts in {
        "first 300 characters": test["text"].str[:300],
        "first 100 characters": test["text"].str[:100],
        "5% OCR errors": test["text"].map(lambda t: ocr_noise(t, 0.05, rng)),
        "15% OCR errors": test["text"].map(lambda t: ocr_noise(t, 0.15, rng)),
    }.items():
        acc = accuracy_score(test["label"], model.predict(texts))
        report["robustness"][name] = round(acc, 4)
        print(f"  {name:<22} accuracy {acc:.4f}")

    # 6. Confidence: how often is the model right when it is sure, and how often does it say "not sure"?
    proba = model.predict_proba(test["text"])
    top = proba.max(axis=1)
    right = model.classes_[proba.argmax(axis=1)] == test["label"].to_numpy()
    report["confidence"] = {}
    for thr in (0.5, 0.7):
        sure = top >= thr
        report["confidence"][str(thr)] = {"share_sure": round(float(sure.mean()), 4),
                                          "accuracy_when_sure": round(float(right[sure].mean()), 4) if sure.any() else None}
    oproba = model.predict_proba(outside["text"]).max(axis=1)
    report["confidence"]["outside_median_top_probability"] = round(float(np.median(oproba)), 4)

    model.fit(data["text"], data["label"])  # final model uses every labelled document
    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump(slim(model), ROOT / "models" / "docusort.joblib", compress=3)
    report["trained_on"] = len(data)
    report["minutes"] = round((time.time() - t0) / 60, 1)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nSaved models/docusort.joblib and reports/metrics.json ({report['minutes']} min)")


if __name__ == "__main__":
    main()
