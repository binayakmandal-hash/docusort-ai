"""D4: find personal numbers in a document and make a redacted copy.

Looks for the identifiers people most often share by accident when they forward a document:
Aadhaar, PAN, payment cards, bank account numbers with IFSC codes, phone numbers, email
addresses, UPI IDs, passport and voter ID numbers, and GSTINs.

Where a number has a built-in check digit, it is verified, which removes most false alarms:
Aadhaar numbers use the Verhoeff algorithm and card numbers use the Luhn algorithm. Patterns
without a checksum (phone, account numbers) only count when they look like that kind of number
and, for account numbers, sit next to words such as "A/c" or "account".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Checksums
# --------------------------------------------------------------------------- #
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Kind:
    id: str
    name: str
    why: str


KINDS = {
    "aadhaar": Kind("aadhaar", "Aadhaar number", "Can be misused for SIM swaps and fake KYC. Share a masked copy (last 4 digits) instead."),
    "pan": Kind("pan", "PAN", "Used for loans and tax filings; often abused in loan fraud."),
    "card": Kind("card", "Card number", "Anyone with the full number can try online payments."),
    "account": Kind("account", "Bank account number", "With the IFSC it's enough to set up debits or target you with fake refund calls."),
    "ifsc": Kind("ifsc", "IFSC code", "Identifies your bank branch; harmless alone but sensitive next to an account number."),
    "phone": Kind("phone", "Phone number", "Lets strangers call or message you, and is used for OTP-based attacks."),
    "email": Kind("email", "Email address", "Invites spam and targeted phishing."),
    "upi": Kind("upi", "UPI ID", "Lets anyone send you payment requests, a common scam route."),
    "passport": Kind("passport", "Passport number", "An identity document number; share only with those who need it."),
    "voter": Kind("voter", "Voter ID number", "An identity document number; share only with those who need it."),
    "gstin": Kind("gstin", "GSTIN", "A business tax ID. Usually fine on invoices, but it contains the PAN."),
}

AADHAAR = re.compile(r"(?<![\d-])(?<!\d )([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4})(?![\s-]?\d)")  # not part of a longer number
PAN = re.compile(r"\b([A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z])\b")
CARD = re.compile(r"(?<!\d)(?<!\d[ -])(\d{4}([ -]?)\d{4}\2\d{4}\2\d{4}(?:\2?\d{1,3})?|\d{4}([ -]?)\d{6}\3\d{5}|\d{13,19})(?![\d])")
# Real card networks: Visa 4, Mastercard 51-55 and 2221-2720, Amex 34/37, RuPay 60/65/81/82/508, Discover 6011.
CARD_PREFIX = re.compile(r"^(4|5[1-5]|2(?:2[2-9][1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720)|3[47]|60|65|81|82|508|6011)")
IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
ACCOUNT = re.compile(r"(?:a/?c|acct|account)\s*(?:no\.?|number|#)?\s*[:.\-]?\s*((?:x+|\*+)?\d[\d\s]{7,19}\d)", re.I)
PHONE = re.compile(r"(?<![\d+])((?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5})(?!\d)")
PHONE_CONTEXT = re.compile(r"(phone|mobile|mob|cell|call|tel|contact|whatsapp|ph)\b", re.I)
EMAIL = re.compile(r"\b([\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
UPI = re.compile(r"\b([\w.-]{2,}@(?:ybl|ibl|axl|paytm|okaxis|okhdfcbank|okicici|oksbi|upi|apl|ptyes|ptsbi|axisbank|icici|sbi|hdfcbank))\b", re.I)
PASSPORT = re.compile(r"(?:passport)\s*(?:no\.?|number|#)?\s*[:.\-]?\s*([A-PR-WY][1-9]\d\s?\d{4}[1-9])\b", re.I)
VOTER = re.compile(r"(?:voter|epic|electoral)[^\n]{0,25}?\b([A-Z]{3}\d{7})\b", re.I)  # needs context: OCR noise often looks like this
GSTIN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def mask(kind: str, value: str) -> str:
    """Keep just enough to recognise the item: last 4 digits, or the first letter of an email name."""
    if kind == "email":
        user, _, domain = value.partition("@")
        return user[:1] + "•" * max(3, len(user) - 1) + "@" + domain
    if kind == "upi":
        user, _, handle = value.partition("@")
        return user[:1] + "•" * max(3, len(user) - 1) + "@" + handle
    keep = 4
    out, seen = [], 0
    alnum = sum(ch.isalnum() for ch in value)
    for ch in value:
        if ch.isalnum():
            seen += 1
            out.append(ch if seen > alnum - keep else "•")
        else:
            out.append(ch)
    return "".join(out)


def find(text: str) -> list[dict]:
    """All sensitive items, without overlaps, in reading order."""
    hits: list[tuple[int, int, str, str]] = []

    def add(kind, m, group=1):
        hits.append((m.start(group), m.end(group), kind, m.group(group)))

    for m in GSTIN.finditer(text):
        add("gstin", m)
    for m in AADHAAR.finditer(text):
        d = _digits(m.group(1))
        looks_like_timestamp = re.fullmatch(r"(19|20)\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{4}", m.group(1))
        if len(d) == 12 and verhoeff_ok(d) and not looks_like_timestamp:
            add("aadhaar", m)
    for m in CARD.finditer(text):
        d = _digits(m.group(1))
        # 13-digit numbers are almost always product barcodes, so cards need 15 to 19 digits.
        if 15 <= len(d) <= 19 and luhn_ok(d) and CARD_PREFIX.match(d) and len(set(d)) > 2:
            add("card", m)
    for m in ACCOUNT.finditer(text):
        if len(_digits(m.group(1))) >= 9:
            add("account", m)
    for rx, kind in ((PAN, "pan"), (IFSC, "ifsc"), (UPI, "upi"), (PASSPORT, "passport"), (VOTER, "voter"), (EMAIL, "email")):
        for m in rx.finditer(text):
            add(kind, m)
    for m in PHONE.finditer(text):
        # A bare 10-digit number counts only with +91/0, the usual 5-5 spacing, or a word like "phone" just before it.
        raw = m.group(1)
        if raw.startswith(("+91", "0")) or re.search(r"\d{5}[\s-]\d{5}", raw) or PHONE_CONTEXT.search(text[max(0, m.start() - 25):m.start()]):
            add("phone", m)

    # Resolve overlaps: earlier patterns in this priority order win.
    priority = ["gstin", "card", "aadhaar", "account", "upi", "pan", "ifsc", "passport", "voter", "phone", "email"]
    hits.sort(key=lambda h: (priority.index(h[2]), h[0]))
    taken: list[tuple[int, int]] = []
    out = []
    for start, end, kind, value in hits:
        if any(start < e and end > s for s, e in taken):
            continue
        taken.append((start, end))
        k = KINDS[kind]
        out.append({"kind": kind, "name": k.name, "why": k.why, "value": value, "masked": mask(kind, value), "start": start, "end": end})
    out.sort(key=lambda h: h["start"])
    return out


def redact(text: str, items: list[dict] | None = None, kinds: set[str] | None = None) -> str:
    """The text with each found item replaced by its masked form."""
    items = find(text) if items is None else items
    out, last = [], 0
    for it in sorted(items, key=lambda h: h["start"]):
        if kinds is not None and it["kind"] not in kinds:
            continue
        out.append(text[last:it["start"]])
        out.append(it["masked"])
        last = it["end"]
    out.append(text[last:])
    return "".join(out)


def summary(items: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    return [{"kind": k, "name": KINDS[k].name, "count": n, "why": KINDS[k].why} for k, n in counts.items()]
