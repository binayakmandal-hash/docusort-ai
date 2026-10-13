"""DocuSort web app.

    python app.py      then open http://127.0.0.1:5000

Drop in documents and DocuSort says what kind each one is, why, pulls out its key details, flags
personal numbers, and for a batch, hands back a zip sorted into folders.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import classifier  # noqa: E402
import fields  # noqa: E402
import reader  # noqa: E402
import sensitive  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
MAX_FILES = 50
MAX_TEXT = 60_000
BATCH_TTL = 15 * 60  # seconds a sorted zip stays available

_batches: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def analyse(text: str, name: str, kind: str = "text", pages: int = 1, ocr: bool = False) -> dict:
    """Everything the page shows for one document."""
    if len(text.split()) < 8:
        return {"file": name, "ok": False, "error": "Almost no readable text. If it's a scan, try a clearer image."}
    result = classifier.classify(text)
    found = sensitive.find(text)
    return {
        **result,
        "file": name, "ok": True, "kind": kind, "pages": pages, "ocr": ocr, "words": len(text.split()),
        "fields": fields.extract(result["label"], text),
        "sensitive": {"summary": sensitive.summary(found),
                      "items": [{k: it[k] for k in ("kind", "name", "masked", "start", "end")} for it in found]},
        "preview": text[:4000],
        "text": text[:MAX_TEXT],
    }


def _cleanup():
    now = time.time()
    with _lock:
        for key in [k for k, (t, _) in _batches.items() if now - t > BATCH_TTL]:
            del _batches[key]


def _safe_name(name: str) -> str:
    name = Path(name).name or "document"
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)[:120]


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
@app.get("/")
def sort_page():
    return render_template("sort.html", page="sort", labels=classifier.LABELS)


@app.get("/accuracy")
def accuracy_page():
    return render_template("accuracy.html", page="accuracy", m=classifier.metrics(), labels=classifier.LABELS)


@app.get("/privacy")
def privacy_page():
    return render_template("privacy.html", page="privacy")


@app.get("/terms")
def terms_page():
    return render_template("terms.html", page="terms")


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return error("Not found", 404)
    return render_template("404.html", page="404"), 404


@app.errorhandler(413)
def too_large(_):
    return error("Those files add up to more than 40 MB. Try fewer or smaller files.", 413)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.post("/api/sort")
def api_sort():
    """One or more files (multipart 'files'), or pasted text (JSON or form 'text')."""
    _cleanup()
    files = request.files.getlist("files")
    if not files:
        payload = request.get_json(silent=True) or request.form
        text = reader.clean(str(payload.get("text") or ""))[:MAX_TEXT]
        if not text:
            return error("Add a file or paste some text first.")
        return jsonify({"ok": True, "batch": None, "documents": [analyse(text, "Pasted text")]})
    if len(files) > MAX_FILES:
        return error(f"Sort up to {MAX_FILES} files at a time.")
    docs, stored = [], []
    for f in files:
        name = _safe_name(f.filename or "document")
        data = f.read()
        try:
            doc = reader.read(name, data)
        except reader.ReadError as exc:
            docs.append({"file": name, "ok": False, "error": str(exc)})
            stored.append({"name": name, "data": data, "result": None, "text": ""})
            continue
        result = analyse(doc.text, name, doc.kind, doc.pages, doc.ocr)
        docs.append(result)
        stored.append({"name": name, "data": data, "result": result if result["ok"] else None, "text": doc.text})
    batch = None
    if len(files) > 1:
        batch = uuid.uuid4().hex
        with _lock:
            _batches[batch] = (time.time(), stored)
    return jsonify({"ok": True, "batch": batch, "documents": docs})


@app.get("/api/batch/<batch>.zip")
def api_batch_zip(batch):
    if not re.fullmatch(r"[0-9a-f]{32}", batch):
        return error("Not found", 404)
    with _lock:
        entry = _batches.get(batch)
    if not entry:
        return error("This sorted batch has expired. Sort the files again to download it.", 404)
    redacted = request.args.get("redacted") == "1"
    buf = io.BytesIO()
    used: set[str] = set()
    rows = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for item in entry[1]:
            r = item["result"]
            folder = "Could not read" if r is None else (r["name"] if r["sure"] else "Not sure")
            path = f"{folder}/{item['name']}"
            stem, n = path, 2
            while path in used:
                p = Path(stem)
                path = f"{p.parent}/{p.stem} ({n}){p.suffix}"
                n += 1
            used.add(path)
            z.writestr(path, item["data"])
            if redacted and r and r["sensitive"]["items"]:
                z.writestr(f"{folder}/{Path(path).stem} (redacted text).txt", sensitive.redact(item["text"]))
            fields_text = "; ".join(f"{f['name']}: {f['value']}" for f in (r or {}).get("fields", []) if f.get("value"))
            rows.append({
                "file": path,
                "type": r["name"] if r else "",
                "confidence": f"{r['confidence']:.2f}" if r else "",
                "sure": ("yes" if r["sure"] else "no") if r else "",
                "key_details": fields_text,
                "sensitive_items": sum(s["count"] for s in r["sensitive"]["summary"]) if r else "",
            })
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["file"])
        w.writeheader()
        w.writerows(rows)
        z.writestr("index.csv", out.getvalue())
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name="docusort-sorted.zip")


@app.post("/api/redact")
def api_redact():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", ""))[:MAX_TEXT]
    if not text.strip():
        return error("Nothing to redact.")
    kinds = payload.get("kinds")
    kinds = {k for k in kinds if k in sensitive.KINDS} if isinstance(kinds, list) else None
    name = _safe_name(str(payload.get("name") or "document"))
    body = sensitive.redact(text, kinds=kinds)
    return Response(body, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{Path(name).stem} (redacted).txt"'})


@app.get("/api/samples")
def api_samples():
    folder = ROOT / "samples"
    return jsonify({"ok": True, "samples": [p.name for p in sorted(folder.glob("*")) if p.is_file()]})


@app.get("/samples/<path:name>")
def sample_file(name):
    path = (ROOT / "samples" / name).resolve()
    if path.parent != (ROOT / "samples").resolve() or not path.is_file():
        return error("Not found", 404)
    return send_file(path)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": classifier.MODEL_PATH.exists()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"\n  DocuSort running at http://127.0.0.1:{port}\n")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)
