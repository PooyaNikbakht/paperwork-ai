"""Text-layer heuristics for demo mode on documents it has never seen.

Deliberately simple: regular expressions over the PDF text layer, with low confidence, so the
review screen shows what a person needs to check. Images have no text layer, so every field
comes back empty and the required-field check sends the document to review.
"""

import re
from typing import Any

from app.models import DocSpec, DocType
from app.values import normalize_date, parse_date, parse_number

AMOUNT = r"[-(]?\$?\s?\d{1,3}(?:[ ,]\d{3})*(?:\.\d{2})|\d+\.\d{2}"

_DATE_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}",
    r"\d{1,2}/\d{1,2}/\d{4}",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}",
    r"\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}",
]
DATE = "(" + "|".join(_DATE_PATTERNS) + ")"


def guess_doc_type(texts: list[str]) -> DocType:
    text = "\n".join(texts).lower()
    if "invoice" in text or "bill to" in text or "amount due" in text:
        return "invoice"
    if "receipt" in text or "subtotal" in text or "visa" in text or "debit" in text:
        return "receipt"
    if text.strip():
        return "custom"
    return "invoice"


def _lines(texts: list[str]) -> list[tuple[int, str]]:
    out = []
    for page, text in enumerate(texts, start=1):
        for line in text.splitlines():
            line = " ".join(line.split())
            if line:
                out.append((page, line))
    return out


def _value(value: Any, page: int, quote: str, confidence: float) -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "source": {"page": page, "quote": quote}}


def _empty() -> dict[str, Any]:
    return {"value": None, "confidence": 0.0, "source": None}


def _find(lines: list[tuple[int, str]], label: str, pattern: str) -> tuple[int, str, str] | None:
    rx = re.compile(rf"{label}[^\d\n]{{0,30}}?({pattern})", re.I)
    for page, line in lines:
        m = rx.search(line)
        if m:
            return page, line, m.group(1)
    return None


def heuristic_extract(texts: list[str], spec: DocSpec) -> dict[str, Any]:
    lines = _lines(texts)
    out: dict[str, Any] = {f.key: _empty() for f in spec.fields}
    if spec.has_lines:
        out["line_items"] = []
        out["taxes"] = []
    if not lines:
        return out

    if spec.doc_type == "custom":
        for f in spec.fields:
            rx = re.compile(rf"^{re.escape(f.label)}\s*[:#-]?\s*(.+)$", re.I)
            for page, line in lines:
                m = rx.match(line)
                if m:
                    out[f.key] = _value(m.group(1).strip(), page, line, 0.5)
                    break
        return out

    name_key = "vendor_name" if spec.doc_type == "invoice" else "merchant_name"
    page, first = lines[0]
    if first.upper() not in ("INVOICE", "RECEIPT"):
        out[name_key] = _value(first, page, first, 0.45)

    if spec.doc_type == "invoice":
        hit = _find(lines, r"invoice\s*(?:no\.?|number|#)", r"[A-Z0-9][A-Z0-9-]{2,}")
        if hit:
            out["invoice_number"] = _value(hit[2], hit[0], hit[1], 0.6)
        due = _find(lines, r"due(?:\s+date)?", DATE)
        if due:
            out["due_date"] = _value(normalize_date(due[2]), due[0], due[1], 0.5)

    date_key = "invoice_date" if spec.doc_type == "invoice" else "date"
    for page, line in lines:
        if "due" in line.lower():
            continue
        m = re.search(DATE, line)
        if m and parse_date(m.group(1)):
            out[date_key] = _value(normalize_date(m.group(1)), page, line, 0.55)
            break

    for key, label in (("subtotal", r"sub\s*-?total"), ("total", r"(?<!sub)(?<!sub )total")):
        hit = None
        for page, line in reversed(lines):
            m = re.search(rf"{label}[^\d\n]{{0,30}}?({AMOUNT})", line, re.I)
            if m:
                hit = (page, line, m.group(1))
                break
        if hit and key in out:
            out[key] = _value(parse_number(hit[2]), hit[0], hit[1], 0.55)

    text = "\n".join(texts)
    if "currency" in out:
        for code in ("USD", "CAD", "EUR", "GBP"):
            if code in text:
                quote = next(line for _, line in lines if code in line)
                out["currency"] = _value(code, 1, quote, 0.6)
                break
        else:
            out["currency"] = {"value": "CAD", "confidence": 0.4, "source": None}

    for page, line in lines:
        m = re.search(
            r"\b(GST|HST|PST|QST|VAT)\b[^\d\n]{0,12}(\d{1,2}(?:\.\d+)?)\s*%[^\d\n]*?("
            + AMOUNT
            + r")\s*$",
            line,
        )
        if m:
            out["taxes"].append(
                {
                    "kind": m.group(1),
                    "rate_percent": float(m.group(2)),
                    "amount": parse_number(m.group(3)),
                    "confidence": 0.5,
                    "source": {"page": page, "quote": line},
                }
            )
    return out
