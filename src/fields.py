"""D2: pull out the details each kind of document is usually opened for.

Rule-based and conservative: a field we can't find stays empty instead of being guessed. Every
value comes with the line it was read from, so the user can check it.
"""
from __future__ import annotations

import re

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(
    rf"\b(\d{{1,2}}[/.-]\d{{1,2}}[/.-](?:19|20)?\d{{2}}|(?:19|20)\d{{2}}[/.-]\d{{1,2}}[/.-]\d{{1,2}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[ -]{MONTHS}[ ,-]+(?:19|20)?\d{{2}}|{MONTHS} \d{{1,2}}(?:st|nd|rd|th)?,? (?:19|20)\d{{2}})\b", re.I)
AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})|\d+\.\d{2})(?![\d.])")
TOTAL_LABEL = re.compile(
    r"\b(grand\s*total|round\w*\s*(?:\w\s+)?total|total\s*rounded|total\s*(?:amount|amt|payable|due|incl\.?|\(rm\)|\(inr\)|rm|rs)|nett?\s*total|amount\s*due|"
    r"total\s*:?|net\s*amount|balance\s*due)", re.I)
NOT_TOTAL = re.compile(r"sub\s*-?\s*total|total\s*(qty|quantity|item|discount|disc|tax|gst|sst|saving|tendered|excl)|exclud|change|cash|rounding", re.I)
COMPANY_HINT = re.compile(r"\b(sdn\.?\s*b[hn]d|sdn|s/b|bhd|pvt\.?|private limited|limited|ltd\.?|llp|inc\.?|corp|enterprise|trading|restaurant|"
                          r"restoran|store|stores|mart|supermarket|hardware|bakery|cafe|kedai|company|co\.)\b", re.I)
AMOUNT_ONLY = re.compile(r"^(?:rm|rs\.?|inr|₹|\$)?\s*-?\s*\d[\d,]*\.\d{2}\s*(?:rm)?$", re.I)
ROUNDING = re.compile(r"round\w*\s*(?:adj\w*|adjustment)", re.I)
REG_NO = re.compile(r"\s*\(?\b\d{4,8}-?[A-Z]\b\)?\s*$")
HEADINGS = re.compile(r"^(tax invoice|invoice|receipt|cash bill|cash sale|official receipt|simplified tax invoice|bill)\b", re.I)
GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
INVOICE_NO = re.compile(r"\b(?:invoice|inv|bill|receipt|document|doc)\s*(?:no|number|#)\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]{2,})", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)|(?<!\d)\+?\d{1,3}[\s-]?\(?\d{2,4}\)?[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)")


def _lines(text: str) -> list[str]:
    return [l.strip() for l in (text or "").splitlines() if l.strip()]


def _field(name: str, value: str | None, line: str | None = None) -> dict:
    return {"name": name, "value": value, "source": (line or "")[:160] if value else None}


def _norm_amount(s: str) -> str:
    return re.sub(r"[,\s]", "", s)


# --------------------------------------------------------------------------- #
# Receipts and invoices
# --------------------------------------------------------------------------- #
TIE = lambda new, old: new > old  # among equally strong labels, the larger amount is the total


def receipt_total(lines: list[str]) -> tuple[str | None, str | None]:
    """Prefer 'rounded total' / 'grand total' / 'total amount' over a bare 'total'. The value can be on the same
    line or on the next lines (OCR often splits label and number). A rounding adjustment is applied if printed."""
    best = None  # (priority, value, line)
    for i, line in enumerate(lines):
        m = TOTAL_LABEL.search(line)
        if not m or NOT_TOTAL.search(line[:m.end() + 8]):
            continue
        label = m.group(1).lower()
        priority = 3 if re.search(r"round|grand|nett?|due|payable", label) else 2 if re.search(r"amount|amt|incl", label) else 1
        value = None
        found = AMOUNT.findall(line[m.end():])
        if found:
            value = found[-1]
        else:
            for nxt in lines[i + 1:i + 3]:
                if AMOUNT_ONLY.match(nxt):
                    value = AMOUNT.findall(nxt)[-1]
                    break
                if re.search(r"[a-z]{3}", nxt, re.I) and not re.fullmatch(r"(rm|rs\.?|inr)", nxt.strip(), re.I):
                    break
        if value:
            v = _norm_amount(value)
            if best is None or priority > best[0] or (priority == best[0] and TIE(float(v), float(best[1]))):
                best = (priority, v, line)
    if not best:
        return None, None
    total, line = best[1], best[2]
    if best[0] < 3:  # not already a rounded total: apply a printed rounding adjustment
        for i, l in enumerate(lines):
            if ROUNDING.search(l):
                cand = AMOUNT.findall(l) or next((AMOUNT.findall(n) for n in lines[i + 1:i + 3] if re.fullmatch(r"\s*-?\s*\d+\.\d{2}\s*", n)), [])
                if cand:
                    adj_line = l if AMOUNT.findall(l) else next(n for n in lines[i + 1:i + 3] if AMOUNT.findall(n))
                    adj = float(cand[-1]) * (-1 if "-" in adj_line else 1)
                    if 0 < abs(adj) < 0.05:
                        total = f"{float(total) + adj:.2f}"
                break
    return total, line


def receipt_company(lines: list[str]) -> tuple[str | None, str | None]:
    for i, line in enumerate(lines[:8]):
        if COMPANY_HINT.search(line) and not HEADINGS.match(line) and sum(c.isalpha() for c in line) >= 4:
            name = REG_NO.sub("", line).strip()
            if name.endswith("&") and i + 1 < len(lines):
                name = f"{name} {lines[i + 1]}"
            return name, line
    for line in lines[:5]:
        letters = sum(c.isalpha() for c in line)
        if letters >= 4 and letters / max(len(line), 1) > .6 and not HEADINGS.match(line) and not DATE.search(line):
            return line, line
    return None, None


def first(rx: re.Pattern, lines: list[str], group: int = 0):
    for line in lines:
        m = rx.search(line)
        if m:
            return m.group(group), line
    return None, None


def receipt_fields(text: str) -> list[dict]:
    lines = _lines(text)
    company, cline = receipt_company(lines)
    date, dline = first(DATE, lines)
    total, tline = receipt_total(lines)
    inv, iline = first(INVOICE_NO, lines, 1)
    gst, gline = first(GSTIN, lines)
    return [_field("Seller", company, cline), _field("Date", date, dline), _field("Total", total, tline),
            _field("Bill or invoice no.", inv, iline), _field("GSTIN", gst, gline)]


# --------------------------------------------------------------------------- #
# Other document types
# --------------------------------------------------------------------------- #
def contract_fields(text: str) -> list[dict]:
    flat = re.sub(r"\s+", " ", text)
    lines = _lines(text)
    title, tline = None, None
    for line in lines[:15]:
        if re.search(r"\b(agreement|contract|lease|deed|license|licence|memorandum|terms)\b", line, re.I) and len(line) <= 90:
            title, tline = line.strip(" *"), line
            break
    parties, pline = None, None
    # "by and between A, a Delaware corporation ("Company") and B ("Distributor")"
    m = re.search(r"\b(?:by and )?between\s+([^,(;]{3,100})[^;]{0,120}?\)?\s+and\s+([^,(;]{3,100}?)(?:\s*\(|,|\.|\s+this\b|\s+dated\b|;)", flat, re.I)
    if m:
        a, b = m.group(1).strip(" .\"'"), m.group(2).strip(" .\"'")
        parties, pline = f"{a}; {b}", m.group(0)
    date, dline = None, None
    m = re.search(r"(?:dated|effective|made and entered into|entered into|made)\s+(?:as of\s+|on\s+|this\s+)?(.{0,30}?" + DATE.pattern + r"|\d{1,2}(?:st|nd|rd|th)? day of [A-Za-z]+,? \d{4})", flat, re.I)
    if m:
        date, dline = (m.group(2) or m.group(1)).strip(), m.group(0)
    if not date:
        m = re.search(r"\b(\d{1,2}(?:st|nd|rd|th)? day of [A-Z][a-z]+,? \d{4})", flat)
        if m:
            date, dline = m.group(1), m.group(0)
    law, lline = None, None
    m = re.search(r"governed by(?: and construed in accordance with)? the laws? of (?:the )?([A-Z][A-Za-z .]{2,40}?)(?:,|\.| without| and)", flat)
    if m:
        law, lline = m.group(1).strip(), m.group(0)
    term, kline = None, None
    m = re.search(r"\b(?:term|period) of\s+((?:\w+\s+)?\(?\d*\)?\s*(?:years?|months?))", flat, re.I)
    if m:
        term, kline = m.group(1).strip(), m.group(0)
    return [_field("Title", title, tline), _field("Parties", parties, pline), _field("Date", date, dline),
            _field("Governing law", law, lline), _field("Term", term, kline)]


def email_fields(text: str) -> list[dict]:
    lines = _lines(text)
    out = []
    for label, rx in (("From", r"^from\s*:\s*(.+)"), ("To", r"^to\s*:\s*(.+)"), ("Subject", r"^subject\s*:\s*(.+)"), ("Date", r"^(?:date|sent)\s*:\s*(.+)")):
        v, l = first(re.compile(rx, re.I), lines[:40], 1)
        out.append(_field(label, v and v.strip()[:120], l))
    emails = sorted(set(EMAIL.findall(text)))[:5]
    out.append(_field("Email addresses", ", ".join(emails) if emails else None, ", ".join(emails)))
    return out


def resume_fields(text: str) -> list[dict]:
    lines = _lines(text)
    name, nline = None, None
    for line in lines[:3]:
        if re.fullmatch(r"[A-Z][a-zA-Z.'-]+(?: [A-Z][a-zA-Z.'-]+){1,3}", line):
            name, nline = line, line
            break
    email, eline = first(EMAIL, lines)
    phone, pline = first(PHONE, lines)
    years, yline = first(re.compile(r"(\d{1,2})\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:\w+\s+){0,2}experience", re.I), lines, 1)
    degree, dline = first(re.compile(r"\b(ph\.?d|master'?s?|m\.?tech|m\.?sc|mba|mca|bachelor'?s?|b\.?tech|b\.?e\.?|b\.?sc|bca|b\.?com|diploma)\b[^.\n]{0,50}", re.I), lines)
    return [_field("Name", name, nline), _field("Email", email, eline), _field("Phone", phone, pline),
            _field("Experience", f"{years} years" if years else None, yline), _field("Education", degree and degree.strip(), dline)]


SECTION = re.compile(r"^\s*([A-Z][A-Z /&]{3,40}):", re.M)


def medical_fields(text: str) -> list[dict]:
    sections = list(dict.fromkeys(s.strip().title() for s in SECTION.findall(text)))[:8]
    diag, dline = first(re.compile(r"(?:diagnos[ie]s|impression|assessment)\s*:?\s*(.{3,140})", re.I), _lines(text), 1)
    meds, mline = first(re.compile(r"medications?\s*:?\s*(.{3,140})", re.I), _lines(text), 1)
    return [_field("Sections", ", ".join(sections) if sections else None, ", ".join(sections)),
            _field("Diagnosis or impression", diag and diag.strip(" ,."), dline), _field("Medications", meds and meds.strip(" ,."), mline)]


def news_fields(text: str) -> list[dict]:
    lines = _lines(text)
    head = lines[0] if lines and len(lines[0]) <= 140 else None
    date, dline = first(DATE, lines[:6])
    return [_field("Headline", head, head), _field("Date", date, dline)]


def paper_fields(text: str) -> list[dict]:
    flat = re.sub(r"\s+", " ", text).strip()
    first_sentence = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0][:240] if flat else None
    m = re.search(r"\b(we (?:propose|present|introduce|show)[^.]{10,200}\.)", flat, re.I)
    return [_field("Opening", first_sentence, first_sentence), _field("Main claim", m and m.group(1), m and m.group(0))]


def form_fields(text: str) -> list[dict]:
    out = []
    for line in _lines(text):
        m = re.match(r"^([A-Za-z][A-Za-z ./#()-]{1,30}):\s*(\S.{0,80})$", line)
        if m:
            out.append(_field(m.group(1).strip().title(), m.group(2).strip(), line))
        if len(out) >= 8:
            break
    labels = [l.rstrip(":") for l in _lines(text) if re.fullmatch(r"[A-Za-z][A-Za-z ./#()-]{1,30}:", l)][:10]
    if labels and len(out) < 3:
        out.append(_field("Fields on the form", ", ".join(labels), ", ".join(labels)))
    return out or [_field("Fields on the form", None)]


EXTRACTORS = {
    "receipt_invoice": receipt_fields, "contract": contract_fields, "email": email_fields, "resume": resume_fields,
    "medical_report": medical_fields, "news_article": news_fields, "scientific_paper": paper_fields, "form": form_fields,
}


def extract(label: str, text: str) -> list[dict]:
    return EXTRACTORS.get(label, lambda t: [])(text)
