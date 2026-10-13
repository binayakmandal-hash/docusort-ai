"""Load the trained model, classify a document and explain the answer.

The explanation is exact for this kind of model: a linear SVM's score for a class is the sum of
(TF-IDF weight of each n-gram in the document) x (the class's weight for that n-gram). We show the
words that added the most to the predicted class, and the ones that pulled hardest towards the
runner-up, so the user can see what the decision was based on.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "docusort.joblib"
METRICS_PATH = ROOT / "reports" / "metrics.json"
MAX_CHARS = 6000
UNSURE_BELOW = 0.5  # below this top probability, say "not sure"

LABELS = {
    "contract": "Contract",
    "email": "Email",
    "form": "Form",
    "medical_report": "Medical report",
    "news_article": "News article",
    "receipt_invoice": "Receipt or invoice",
    "resume": "Resume",
    "scientific_paper": "Research paper",
}


@lru_cache(maxsize=1)
def model():
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def metrics() -> dict:
    try:
        return json.loads(METRICS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _parts():
    m = model()
    union, calibrated = m.steps[0][1], m.steps[1][1]
    svm = calibrated.calibrated_classifiers_[0].estimator
    return union, svm


def explain(text: str, label: str, versus: str | None = None, k: int = 8) -> dict:
    """Words (word n-grams only, they are readable) that pushed towards `label`, and towards `versus`."""
    union, svm = _parts()
    classes = list(model().classes_)
    word_vec = union.transformer_list[0][1]
    x = word_vec.transform([text])  # word features are the first block of the union
    names = word_vec.get_feature_names_out()
    idx = x.indices
    if not len(idx):
        return {"for": [], "against": []}
    w = x.data
    coef = svm.coef_
    ci = classes.index(label)
    contrib = w * coef[ci, idx]
    order = np.argsort(-contrib)
    readable = np.array([any(ch.isalpha() for ch in names[i]) for i in idx])  # skip bare numbers like "00"
    pro = [{"term": str(names[idx[j]]), "weight": round(float(contrib[j]), 4)} for j in order if contrib[j] > 0 and readable[j]][:k]
    con = []
    if versus:
        vi = classes.index(versus)
        diff = w * (coef[vi, idx] - coef[ci, idx])
        order = np.argsort(-diff)
        con = [{"term": str(names[idx[j]]), "weight": round(float(diff[j]), 4)} for j in order if diff[j] > 0 and readable[j]][:k // 2]
    return {"for": pro, "against": con}


def classify(text: str) -> dict:
    text = (text or "")[:MAX_CHARS]
    m = model()
    proba = m.predict_proba([text])[0]
    order = np.argsort(-proba)
    classes = m.classes_
    top, second = classes[order[0]], classes[order[1]]
    confidence = float(proba[order[0]])
    return {
        "label": top,
        "name": LABELS[top],
        "confidence": round(confidence, 4),
        "sure": confidence >= UNSURE_BELOW,
        "runner_up": {"label": second, "name": LABELS[second], "probability": round(float(proba[order[1]]), 4)},
        "probabilities": [{"label": classes[i], "name": LABELS[classes[i]], "probability": round(float(proba[i]), 4)} for i in order],
        "explanation": explain(text, top, second),
    }
