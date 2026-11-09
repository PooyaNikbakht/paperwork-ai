"""The "trust but verify" layer: checks that catch AI misreads and problems in the documents.

Every check is a small pure function of the extraction and some context. Each returns a status
(pass, warn, fail or skip), a plain-language message, and the field paths involved, so the
review screen can point at exactly what to fix.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import Check, CheckStatus, DocStatus, Extraction
from app.values import CURRENCIES, EMAIL, fmt_money, money_close, parse_date

# Canadian sales tax rates, in percent.
KNOWN_RATES: dict[str, list[float]] = {
    "GST": [5.0],
    "HST": [13.0, 14.0, 15.0],
    "PST": [6.0, 7.0, 8.0],
    "QST": [9.975],
}
RATE_HINTS = {
    "GST": "GST is 5%",
    "HST": "HST is 13% in Ontario and 15% in the Atlantic provinces",
    "PST": "PST is 6% (SK), 7% (BC, MB) or 8%",
    "QST": "QST is 9.975%",
}

TAX_TOLERANCE = 0.02  # tax is sometimes rounded per line


@dataclass
class DuplicateHit:
    doc_id: str
    filename: str
    same_batch: bool
    approved: bool


@dataclass
class CheckContext:
    page_texts: list[str] = field(default_factory=list)
    has_text_layer: bool = False
    duplicates: list[DuplicateHit] = field(default_factory=list)
    today: date = field(default_factory=date.today)
    low_confidence: float = 0.7


def _check(
    id: str, label: str, status: CheckStatus, message: str, fields: list[str] | None = None
) -> Check:
    return Check(id=id, label=label, status=status, message=message, fields=fields or [])


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _cur(ex: Extraction) -> str:
    c = ex.value("currency")
    return f" {c}" if isinstance(c, str) and c else ""


# ---- Checks ----


def check_required(ex: Extraction, _: CheckContext) -> Check:
    missing = [f for f in ex.fields if f.required and (f.value is None or f.value == "")]
    if missing:
        return _check(
            "required",
            "Required fields",
            "fail",
            f"Missing {_join([f.label for f in missing])}. Fill in what's on the document.",
            [f.key for f in missing],
        )
    return _check("required", "Required fields", "pass", "Every required field has a value.")


def check_line_math(ex: Extraction, _: CheckContext) -> Check:
    label = "Line math"
    bad, checked = [], 0
    for i, li in enumerate(ex.line_items):
        if li.quantity is None or li.unit_price is None or li.amount is None:
            continue
        checked += 1
        expected = round(li.quantity * li.unit_price, 2)
        if not money_close(expected, li.amount, 0.015):
            bad.append((i, li, expected))
    if not checked:
        return _check("line_math", label, "skip", "No lines with a quantity, price and amount.")
    if bad:
        parts = [
            f"line {i + 1}: {li.quantity:g} × {fmt_money(li.unit_price or 0)} = "
            f"{fmt_money(expected)}, but the amount says {fmt_money(li.amount or 0)}"
            for i, li, expected in bad
        ]
        return _check(
            "line_math",
            label,
            "fail",
            "Quantity times unit price doesn't match on " + "; ".join(parts) + ".",
            [f"line_items.{i}.amount" for i, _, _ in bad],
        )
    return _check(
        "line_math", label, "pass", f"Quantity × unit price matches on all {checked} lines."
    )


def check_line_items_sum(ex: Extraction, _: CheckContext) -> Check:
    label = "Line items add up"
    amounts = [li.amount for li in ex.line_items if li.amount is not None]
    if not amounts:
        return _check("line_items_sum", label, "skip", "No line items to add up.")
    total_lines = round(sum(amounts), 2)
    subtotal = ex.money("subtotal")
    target_label, fields = "the subtotal", ["subtotal"]
    if subtotal is None:
        total = ex.money("total")
        if total is None:
            return _check("line_items_sum", label, "skip", "No subtotal or total to compare with.")
        subtotal = round(total - sum(t.amount or 0 for t in ex.taxes) - (ex.money("tip") or 0), 2)
        target_label, fields = "the total minus taxes", ["total"]
    if money_close(total_lines, subtotal):
        return _check(
            "line_items_sum",
            label,
            "pass",
            f"{len(amounts)} line items add up to {target_label} "
            f"({fmt_money(subtotal)}{_cur(ex)}).",
        )
    diff = round(subtotal - total_lines, 2)
    return _check(
        "line_items_sum",
        label,
        "fail",
        f"Line items add up to {fmt_money(total_lines)}, but {target_label} is "
        f"{fmt_money(subtotal)}, a difference of {fmt_money(abs(diff))}. "
        "Either a line was misread or the document itself is wrong.",
        [*fields, *_suspect_lines(ex)],
    )


def _suspect_lines(ex: Extraction) -> list[str]:
    """Lines worth looking at when the sum is off: bad math or low confidence, else all."""
    suspects = [
        f"line_items.{i}.amount"
        for i, li in enumerate(ex.line_items)
        if (
            li.quantity is not None
            and li.unit_price is not None
            and li.amount is not None
            and not money_close(round(li.quantity * li.unit_price, 2), li.amount)
        )
        or (not li.edited and li.confidence < 0.7)
    ]
    return suspects or [f"line_items.{i}.amount" for i in range(len(ex.line_items))]


def check_totals(ex: Extraction, _: CheckContext) -> Check:
    label = "Totals add up"
    subtotal, total = ex.money("subtotal"), ex.money("total")
    if subtotal is None or total is None:
        return _check("totals", label, "skip", "Needs both a subtotal and a total.")
    taxes = round(sum(t.amount or 0 for t in ex.taxes), 2)
    tip = ex.money("tip") or 0
    expected = round(subtotal + taxes + tip, 2)
    parts = [f"subtotal {fmt_money(subtotal)}"]
    if ex.taxes:
        parts.append(f"taxes {fmt_money(taxes)}")
    if tip:
        parts.append(f"tip {fmt_money(tip)}")
    if money_close(expected, total):
        return _check(
            "totals",
            label,
            "pass",
            f"{_join(parts).capitalize()} equal the total ({fmt_money(total)}{_cur(ex)}).",
        )
    diff = round(total - expected, 2)
    return _check(
        "totals",
        label,
        "fail",
        f"{_join(parts).capitalize()} come to {fmt_money(expected)}, but the total says "
        f"{fmt_money(total)}, a difference of {fmt_money(abs(diff))}.",
        ["subtotal", "total", *[f"taxes.{i}.amount" for i in range(len(ex.taxes))]],
    )


def check_tax_rates(ex: Extraction, _: CheckContext) -> Check:
    label = "Tax rates"
    if not ex.taxes:
        return _check("tax_rates", label, "skip", "No taxes on this document.")
    subtotal = ex.money("subtotal")
    worst: CheckStatus = "pass"
    notes: list[str] = []
    fields: list[str] = []
    order = {"pass": 0, "warn": 1, "fail": 2}

    def flag(status: CheckStatus, note: str, path: str) -> None:
        nonlocal worst
        if order[status] > order[worst]:
            worst = status
        notes.append(note)
        if status != "pass":
            fields.append(path)

    for i, t in enumerate(ex.taxes):
        path = f"taxes.{i}.amount"
        known = KNOWN_RATES.get(t.kind)
        rate = t.rate
        if known and rate is not None and not any(abs(rate - k) < 0.001 for k in known):
            flag("warn", f"{RATE_HINTS[t.kind]}; this says {rate:g}%.", f"taxes.{i}.rate")
            continue
        if t.amount is None or subtotal is None or subtotal <= 0:
            continue
        if rate is None:
            implied = t.amount / subtotal * 100
            if known and not any(abs(implied - k) < 0.05 for k in known):
                flag(
                    "warn",
                    f"{t.kind} works out to {implied:.2f}% of the subtotal. {RATE_HINTS[t.kind]}.",
                    path,
                )
            continue
        expected = round(subtotal * rate / 100, 2)
        if t.amount > expected + TAX_TOLERANCE:
            flag(
                "fail",
                f"{t.kind} at {rate:g}% of {fmt_money(subtotal)} is {fmt_money(expected)}, "
                f"but the document charges {fmt_money(t.amount)}.",
                path,
            )
        elif t.amount < expected - TAX_TOLERANCE:
            base = t.amount / rate * 100
            note = (
                f"{t.kind} is {rate:g}% of {fmt_money(base)}, not the whole subtotal. "
                "That's normal when some items are tax-exempt."
            )
            flag("pass" if ex.doc_type == "receipt" else "warn", note, path)
    if worst == "pass" and not notes:
        kinds = _join([f"{t.kind} {t.rate:g}%" if t.rate is not None else t.kind for t in ex.taxes])
        return _check("tax_rates", label, "pass", f"{kinds} match the subtotal.")
    return _check("tax_rates", label, worst, " ".join(notes), fields)


def check_dates(ex: Extraction, ctx: CheckContext) -> Check:
    label = "Dates"
    dated = [f for f in ex.fields if f.type == "date" and f.value not in (None, "")]
    if not dated:
        return _check("dates", label, "skip", "No dates to check.")
    problems: list[tuple[CheckStatus, str, str]] = []
    parsed: dict[str, date] = {}
    for f in dated:
        d = parse_date(str(f.value))
        if d is None:
            problems.append(("fail", f"{f.label} “{f.value}” isn't a date I can read.", f.key))
            continue
        parsed[f.key] = d
        if d > ctx.today + timedelta(days=366):
            problems.append(("warn", f"{f.label} is more than a year from now.", f.key))
        elif d < ctx.today - timedelta(days=365 * 7):
            problems.append(("warn", f"{f.label} is more than seven years ago.", f.key))
    issued, due = parsed.get("invoice_date"), parsed.get("due_date")
    if issued and due and due < issued:
        problems.append(("fail", "The due date is before the invoice date.", "due_date"))
    if not problems:
        listed = _join([f"{f.label.lower()} {parsed[f.key].strftime('%b %-d, %Y')}" for f in dated])
        return _check("dates", label, "pass", f"Dates are valid: {listed}.")
    status: CheckStatus = "fail" if any(s == "fail" for s, _, _ in problems) else "warn"
    return _check(
        "dates", label, status, " ".join(m for _, m, _ in problems), [k for _, _, k in problems]
    )


_CURRENCY_MARKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(CAD|USD|EUR|GBP|AUD)\b"), ""),
    (re.compile(r"US\$"), "USD"),
    (re.compile(r"\bC\$|CA\$"), "CAD"),
    (re.compile(r"€"), "EUR"),
    (re.compile(r"£"), "GBP"),
]


def _mentioned_currencies(texts: list[str]) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for rx, code in _CURRENCY_MARKERS:
            for m in rx.finditer(text):
                found.add(code or m.group(1))
    return found


def check_currency(ex: Extraction, ctx: CheckContext) -> Check:
    label = "Currency"
    value = ex.value("currency")
    if not value:
        return _check("currency", label, "skip", "No currency to check.")
    code = str(value)
    if code not in CURRENCIES:
        return _check(
            "currency",
            label,
            "fail",
            f"“{code}” isn't a currency code I know. Use an ISO code such as CAD or USD.",
            ["currency"],
        )
    quotes = [s.quote for s in _sources(ex)]
    others = sorted(_mentioned_currencies([*ctx.page_texts, *quotes]) - {code})
    if others:
        return _check(
            "currency",
            label,
            "fail",
            f"The currency is set to {code}, but the document also mentions {_join(others)}. "
            "Check which currency the amounts are really in before paying or booking it.",
            ["currency", "total"],
        )
    return _check("currency", label, "pass", f"{CURRENCIES[code]} ({code}) is used consistently.")


def check_duplicate(ex: Extraction, ctx: CheckContext) -> Check:
    label = "Duplicates"
    vendor, number = ex.value("vendor_name"), ex.value("invoice_number")
    if not vendor or not number:
        return _check("duplicate", label, "skip", "Needs a vendor and an invoice number.")
    if not ctx.duplicates:
        return _check("duplicate", label, "pass", f"No other invoice {number} from {vendor}.")
    hit = ctx.duplicates[0]
    where = "earlier in this batch" if hit.same_batch else "in a batch you already approved"
    return _check(
        "duplicate",
        label,
        "fail",
        f"Invoice {number} from {vendor} already appears {where} (“{hit.filename}”). "
        "Paying both would pay the same bill twice.",
        ["vendor_name", "invoice_number"],
    )


def _sources(ex: Extraction) -> list:
    out = [f.source for f in ex.fields if f.source]
    out += [li.source for li in ex.line_items if li.source]
    out += [t.source for t in ex.taxes if t.source]
    return out


def check_sources(ex: Extraction, ctx: CheckContext) -> Check:
    label = "Sources found on the page"
    if not ctx.has_text_layer:
        return _check(
            "sources",
            label,
            "skip",
            "Scans and photos have no text layer, so quotes can't be matched automatically. "
            "Use “Show source” to compare by eye.",
        )
    missing_labels, paths = [], []
    for f in ex.fields:
        if f.source and f.source.found is False and not f.edited:
            missing_labels.append(f.label)
            paths.append(f.key)
    for i, li in enumerate(ex.line_items):
        if li.source and li.source.found is False and not li.edited:
            missing_labels.append(f"line {i + 1}")
            paths.append(f"line_items.{i}.description")
    for i, t in enumerate(ex.taxes):
        if t.source and t.source.found is False and not t.edited:
            missing_labels.append(t.kind)
            paths.append(f"taxes.{i}.amount")
    if missing_labels:
        return _check(
            "sources",
            label,
            "warn",
            f"Couldn't find the quoted text for {_join(missing_labels)} on the page. "
            "The value may not be on the document, so check it.",
            paths,
        )
    n = sum(1 for s in _sources(ex) if s.found)
    return _check("sources", label, "pass", f"All {n} quoted sources were found on the page.")


def check_confidence(ex: Extraction, ctx: CheckContext) -> Check:
    label = "AI confidence"
    unsure: list[tuple[str, str, float]] = []
    for f in ex.fields:
        if f.value is not None and not f.edited and f.confidence < ctx.low_confidence:
            unsure.append((f.label, f.key, f.confidence))
    for i, li in enumerate(ex.line_items):
        if not li.edited and li.confidence < ctx.low_confidence:
            unsure.append((f"line {i + 1}", f"line_items.{i}.amount", li.confidence))
    for i, t in enumerate(ex.taxes):
        if not t.edited and t.confidence < ctx.low_confidence:
            unsure.append((t.kind, f"taxes.{i}.amount", t.confidence))
    if unsure:
        listed = _join([f"{name} ({c:.0%})" for name, _, c in unsure])
        return _check(
            "confidence",
            label,
            "warn",
            f"The AI wasn't sure about {listed}. Compare with the page.",
            [k for _, k, _ in unsure],
        )
    return _check("confidence", label, "pass", "The AI was confident about every value.")


def check_formats(ex: Extraction, _: CheckContext) -> Check:
    label = "Formats"
    bad = [f for f in ex.fields if f.type == "email" and f.value and not EMAIL.match(str(f.value))]
    if bad:
        return _check(
            "formats",
            label,
            "fail",
            f"{_join([f.label for f in bad])} doesn't look like an email address.",
            [f.key for f in bad],
        )
    return _check("formats", label, "pass", "Values have the expected formats.")


Rule = Callable[[Extraction, CheckContext], Check]

RULES: dict[str, list[Rule]] = {
    "invoice": [
        check_required,
        check_line_math,
        check_line_items_sum,
        check_totals,
        check_tax_rates,
        check_dates,
        check_currency,
        check_duplicate,
        check_sources,
        check_confidence,
    ],
    "receipt": [
        check_required,
        check_line_math,
        check_line_items_sum,
        check_totals,
        check_tax_rates,
        check_dates,
        check_currency,
        check_sources,
        check_confidence,
    ],
    "custom": [check_required, check_formats, check_dates, check_sources, check_confidence],
}


def run_checks(ex: Extraction, ctx: CheckContext) -> list[Check]:
    return [rule(ex, ctx) for rule in RULES[ex.doc_type]]


def status_for(checks: list[Check]) -> DocStatus:
    """Anything to look at sends the document to review; otherwise it's ready to approve."""
    return "needs_review" if any(c.status in ("fail", "warn") for c in checks) else "ready"
