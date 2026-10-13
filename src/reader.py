"""Get plain text out of an uploaded document: PDF, Word (.docx), plain text or an image.

Images (and PDFs with no text layer, such as scans) go through Tesseract OCR when it is
installed. Nothing here writes the file to disk.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 6000  # the model was trained on the first 6,000 characters of each document

TEXT_TYPES = {".txt", ".md", ".csv", ".eml"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


class ReadError(ValueError):
    """The file can't be read; the message is safe to show to the user."""


@dataclass
class Document:
    text: str
    kind: str          # pdf | docx | text | image
    pages: int = 1
    ocr: bool = False  # True when the text came from OCR

    @property
    def words(self) -> int:
        return len(self.text.split())


def _ext(name: str) -> str:
    m = re.search(r"(\.[A-Za-z0-9]+)$", name or "")
    return m.group(1).lower() if m else ""


def _ocr(image) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise ReadError("Reading images needs Tesseract OCR, which isn't installed on this server. "
                        "Upload a PDF, Word or text file, or paste the text.") from exc
    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise ReadError("Reading images needs Tesseract OCR, which isn't installed on this server. "
                        "Upload a PDF, Word or text file, or paste the text.") from exc


def _pdf(data: bytes) -> Document:
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = pdf.pages[:20]
            text = "\n".join((p.extract_text() or "") for p in pages)
            if len(text.split()) >= 15:
                return Document(text, "pdf", len(pdf.pages))
            # Probably a scan: OCR the first few pages.
            images = [p.to_image(resolution=200).original for p in pages[:3]]
    except Exception as exc:  # pdfplumber raises several unrelated types for broken files
        raise ReadError("That PDF couldn't be opened. It may be damaged or password-protected.") from exc
    return Document("\n".join(_ocr(im) for im in images), "pdf", len(pages), ocr=True)


def _docx(data: bytes) -> Document:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ReadError("That Word file couldn't be opened. Save it as .docx or PDF and try again.") from exc
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        text = text.replace(a, b)
    return Document(text, "docx")


def _image(data: bytes) -> Document:
    from PIL import Image, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ReadError("That file doesn't look like a valid image.") from exc
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return Document(_ocr(img), "image", ocr=True)


def read(name: str, data: bytes) -> Document:
    """Read an uploaded file. Raises ReadError with a user-facing message."""
    if len(data) > MAX_BYTES:
        raise ReadError("That file is larger than 10 MB.")
    ext = _ext(name)
    if ext == ".pdf" or data[:5] == b"%PDF-":
        doc = _pdf(data)
    elif ext == ".docx":
        doc = _docx(data)
    elif ext in IMAGE_TYPES:
        doc = _image(data)
    elif ext in TEXT_TYPES:
        doc = Document(data.decode("utf-8", errors="ignore"), "text")
    elif ext == ".doc":
        raise ReadError("Old .doc files aren't supported. Save it as .docx or PDF and try again.")
    else:
        raise ReadError("Upload a PDF, Word (.docx), text file or an image (PNG or JPG).")
    doc.text = clean(doc.text)
    return doc


def clean(text: str) -> str:
    text = (text or "").replace("\r", "").replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()
