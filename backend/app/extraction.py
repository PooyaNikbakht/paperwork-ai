"""Turning a provider's raw output into the stored `Extraction`, and locating its sources."""

from typing import Any

from app.categories import (
    Suggestion,
    clean_category,
    suggest_for_line,
    summarize_receipt,
)
from app.models import (
    Box,
    DocSpec,
    ExtractedField,
    Extraction,
    FieldSpec,
    LineItem,
    Source,
    TaxLine,
    Value,
)
from app.pages import QuoteLocator
from app.values import normalize_currency, normalize_date, parse_number

_TAX_KINDS = {"GST", "HST", "PST", "QST", "VAT", "Sales tax", "Other"}
_TAX_ALIASES = {"TVQ": "QST", "TPS": "GST", "TVH": "HST", "SALES TAX": "Sales tax", "RST": "PST"}


def coerce(spec: FieldSpec, value: Any) -> Value:
    """A field value in its canonical form: numbers as floats, dates as ISO, codes upper case."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if spec.type in ("money", "number"):
        return parse_number(value)
    if spec.type == "date":
        return normalize_date(str(value))
    if spec.type == "currency":
        return normalize_currency(value)
    return " ".join(str(value).split())


def _confidence(raw: Any) -> float:
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return 0.0
    # Some models answer in percent.
    if c > 1:
        c = c / 100
    return round(min(max(c, 0.0), 1.0), 3)


def _source(raw: Any) -> Source | None:
    if not isinstance(raw, dict) or not raw.get("quote"):
        return None
    try:
        page = max(1, int(raw.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    boxes = [Box(**b) for b in raw.get("boxes") or [] if isinstance(b, dict)]
    return Source(page=page, quote=str(raw["quote"])[:300], boxes=boxes)


def _tax_kind(raw: Any) -> str:
    kind = str(raw or "Other").strip()
    kind = _TAX_ALIASES.get(kind.upper(), kind)
    upper = kind.upper()
    if upper in _TAX_KINDS:
        return upper
    return kind if kind in _TAX_KINDS else "Other"


def _reason(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:160]


def apply_categories(ex: Extraction, raw: dict[str, Any], raw_lines: list[dict[str, Any]]) -> None:
    """Suggested categories for a receipt: the provider's answer when it is on the list, else the
    rule-based categorizer. Either way the result is always one of `CATEGORIES`."""
    vendor = ex.value("merchant_name")
    vendor = vendor if isinstance(vendor, str) else None
    for line, item in zip(ex.line_items, raw_lines, strict=False):
        category = clean_category(item.get("category"))
        if category:
            line.category, line.category_reason = category, _reason(item.get("category_reason"))
        else:
            fallback = suggest_for_line(line.description, vendor)
            line.category, line.category_reason = fallback.category, fallback.reason
    ai = raw.get("expense_category")
    ai_category = clean_category(ai.get("category")) if isinstance(ai, dict) else None
    if ai_category:
        top = Suggestion(ai_category, _reason(ai.get("reason")))
    else:
        top = summarize_receipt(
            [(li.category or "Other", li.amount or 0.0) for li in ex.line_items], vendor
        )
    ex.category, ex.category_reason = top.category, top.reason


def normalize(raw: dict[str, Any], spec: DocSpec) -> Extraction:
    fields = []
    for f in spec.fields:
        item = raw.get(f.key) or {}
        value = coerce(f, item.get("value"))
        fields.append(
            ExtractedField(
                key=f.key,
                label=f.label,
                type=f.type,
                required=f.required,
                value=value,
                original=value,
                confidence=_confidence(item.get("confidence")) if value is not None else 0.0,
                source=_source(item.get("source")) if value is not None else None,
            )
        )
    lines: list[LineItem] = []
    taxes: list[TaxLine] = []
    if spec.has_lines:
        for item in raw.get("line_items") or []:
            lines.append(
                LineItem(
                    description=" ".join(str(item.get("description") or "").split()),
                    quantity=parse_number(item.get("quantity")),
                    unit_price=parse_number(item.get("unit_price")),
                    amount=parse_number(item.get("amount")),
                    confidence=_confidence(item.get("confidence")),
                    source=_source(item.get("source")),
                )
            )
        for item in raw.get("taxes") or []:
            amount = parse_number(item.get("amount"))
            if amount is None:
                continue
            taxes.append(
                TaxLine(
                    kind=_tax_kind(item.get("kind")),  # type: ignore[arg-type]
                    rate=parse_number(item.get("rate_percent", item.get("rate"))),
                    amount=amount,
                    confidence=_confidence(item.get("confidence")),
                    source=_source(item.get("source")),
                )
            )
    ex = Extraction(
        doc_type=spec.doc_type,
        has_lines=spec.has_lines,
        fields=fields,
        line_items=lines,
        taxes=taxes,
    )
    if spec.doc_type == "receipt":
        apply_categories(ex, raw, list(raw.get("line_items") or []))
    return ex


def all_sources(ex: Extraction) -> list[Source]:
    out = [f.source for f in ex.fields if f.source]
    out += [li.source for li in ex.line_items if li.source]
    out += [t.source for t in ex.taxes if t.source]
    return out


def locate_sources(ex: Extraction, pdf_bytes: bytes | None, has_text_layer: bool) -> None:
    """Find each quote on its page and record highlight boxes, in place.

    Only PDFs with a text layer can be checked. For images, boxes come from the provider (if
    any) and `found` stays None, meaning "not checked".
    """
    if pdf_bytes is None or not has_text_layer:
        return
    with QuoteLocator(pdf_bytes) as locator:
        for src in all_sources(ex):
            hit = locator.find_any_page(src.quote, src.page)
            if hit:
                src.page, src.boxes = hit
                src.found = True
            else:
                src.boxes = []
                src.found = False
