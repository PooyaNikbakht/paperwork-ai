"""Exports: CSV (one row per document or per line), Google Sheets CSV, Excel, and JSON."""

import csv
import io
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.categories import CATEGORIES, DISCLAIMER, OTHER
from app.models import Extraction
from app.store import Document
from app.values import parse_date

ExportFormat = Literal["csv", "csv-lines", "csv-categories", "sheets", "xlsx", "json"]

MEDIA = {
    "csv": "text/csv; charset=utf-8",
    "csv-lines": "text/csv; charset=utf-8",
    "csv-categories": "text/csv; charset=utf-8",
    "sheets": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
}
EXTENSION = {
    "csv": "csv",
    "csv-lines": "csv",
    "csv-categories": "csv",
    "sheets": "csv",
    "xlsx": "xlsx",
    "json": "json",
}

# Common columns across document types, in the order a bookkeeper expects them.
PARTY = {"invoice": "vendor_name", "receipt": "merchant_name"}
NUMBER = {"invoice": "invoice_number"}
DATE = {"invoice": "invoice_date", "receipt": "date"}

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: Any) -> Any:
    """Neutralize spreadsheet formula injection in text cells (numbers pass through)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _tax_total(ex: Extraction, kind: str) -> float | None:
    amounts = [t.amount for t in ex.taxes if t.kind == kind and t.amount is not None]
    return round(sum(amounts), 2) if amounts else None


def _issue_count(doc: Document) -> int:
    return sum(1 for c in doc.checks if c.status in ("fail", "warn"))


def has_receipts(docs: Iterable[Document]) -> bool:
    return any(d.extraction and d.extraction.doc_type == "receipt" for d in docs)


def document_columns(docs: list[Document]) -> list[str]:
    """Header for one-row-per-document exports. Custom fields add their own columns."""
    cols = [
        "file",
        "type",
        "status",
        "party",
        "number",
        "date",
        "due_date",
        "currency",
        "subtotal",
        "gst",
        "hst",
        "pst",
        "qst",
        "other_tax",
        "tip",
        "total",
        "payment_method",
    ]
    extra: list[str] = []
    for d in docs:
        if d.extraction and d.extraction.doc_type == "custom":
            for f in d.extraction.fields:
                if f.key not in extra and f.key not in cols:
                    extra.append(f.key)
    if has_receipts(docs):
        cols += ["category", "category_reason", "job"]
    return [*cols, *extra, "checks_flagged", "edited_fields", "provider"]


def document_row(doc: Document) -> dict[str, Any]:
    ex = doc.extraction
    row: dict[str, Any] = {
        "file": doc.filename,
        "type": doc.doc_type or "",
        "status": doc.status,
        "checks_flagged": _issue_count(doc),
        "provider": "demo" if doc.provider == "mock" else (doc.provider or ""),
    }
    if ex is None:
        return row
    t = ex.doc_type
    row.update(
        {
            "party": ex.value(PARTY.get(t, "")) or "",
            "number": ex.value(NUMBER.get(t, "")) or "",
            "date": ex.value(DATE.get(t, "")) or "",
            "due_date": ex.value("due_date") or "",
            "currency": ex.value("currency") or "",
            "subtotal": ex.money("subtotal"),
            "gst": _tax_total(ex, "GST"),
            "hst": _tax_total(ex, "HST"),
            "pst": _tax_total(ex, "PST"),
            "qst": _tax_total(ex, "QST"),
            "other_tax": round(
                sum(t.amount or 0 for t in ex.taxes if t.kind not in ("GST", "HST", "PST", "QST")),
                2,
            )
            or None,
            "tip": ex.money("tip"),
            "total": ex.money("total"),
            "payment_method": ex.value("payment_method") or "",
            "edited_fields": sum(1 for f in ex.fields if f.edited)
            + sum(1 for li in ex.line_items if li.edited),
        }
    )
    if t == "custom":
        for f in ex.fields:
            row[f.key] = f.value
    if t == "receipt":
        row.update(category=ex.category or "", category_reason=ex.category_reason, job=ex.job or "")
    return row


LINE_COLUMNS = [
    "file",
    "party",
    "number",
    "date",
    "currency",
    "line",
    "description",
    "quantity",
    "unit_price",
    "amount",
]


RECEIPT_LINE_COLUMNS = ["job", "category", "category_reason"]


def line_columns(docs: Iterable[Document]) -> list[str]:
    return [*LINE_COLUMNS, *RECEIPT_LINE_COLUMNS] if has_receipts(docs) else LINE_COLUMNS


def line_rows(docs: Iterable[Document]) -> list[dict[str, Any]]:
    rows = []
    for doc in docs:
        ex = doc.extraction
        if ex is None or not ex.has_lines:
            continue
        base = document_row(doc)
        for i, li in enumerate(ex.line_items, start=1):
            rows.append(
                {
                    "file": doc.filename,
                    "party": base.get("party", ""),
                    "number": base.get("number", ""),
                    "date": base.get("date", ""),
                    "currency": base.get("currency", ""),
                    "line": i,
                    "description": li.description,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "amount": li.amount,
                    "job": ex.job or "",
                    "category": li.category or "",
                    "category_reason": li.category_reason,
                }
            )
    return rows


# ---- Per-category summary (receipts) ----

SUMMARY_COLUMNS = ["category", "receipts", "line_items", "amount_before_tax", "tax", "total"]


def category_summary(docs: list[Document]) -> list[dict[str, Any]]:
    """Totals per suggested category. Tax is shared across a receipt's lines in proportion to
    their amounts, so each category's total includes its part of the tax."""
    buckets: dict[str, dict[str, Any]] = {}

    def add(category: str, doc_id: str, amount: float, tax: float, lines: int) -> None:
        b = buckets.setdefault(category, {"docs": set(), "lines": 0, "amount": 0.0, "tax": 0.0})
        b["docs"].add(doc_id)
        b["lines"] += lines
        b["amount"] += amount
        b["tax"] += tax

    for doc in docs:
        ex = doc.extraction
        if ex is None or ex.doc_type != "receipt":
            continue
        tax_total = sum(t.amount or 0 for t in ex.taxes)
        priced = [li for li in ex.line_items if li.amount is not None]
        base = sum(li.amount or 0 for li in priced)
        if priced and base:
            for li in priced:
                share = (li.amount or 0) / base
                add(li.category or OTHER, doc.id, li.amount or 0, tax_total * share, 1)
        else:
            amount = ex.money("subtotal")
            if amount is None and (total := ex.money("total")) is not None:
                amount = total - tax_total
            add(ex.category or OTHER, doc.id, amount or 0, tax_total, 0)
    rows = []
    for category in [*CATEGORIES, *(c for c in buckets if c not in CATEGORIES)]:
        b = buckets.get(category)
        if b is None:
            continue
        amount, tax = round(b["amount"], 2), round(b["tax"], 2)
        rows.append(
            {
                "category": category,
                "receipts": len(b["docs"]),
                "line_items": b["lines"],
                "amount_before_tax": amount,
                "tax": tax,
                "total": round(amount + tax, 2),
            }
        )
    return rows


def summary_with_total(docs: list[Document]) -> list[dict[str, Any]]:
    rows = category_summary(docs)
    if rows:
        rows.append(
            {
                "category": "All categories",
                "receipts": len(
                    {d.id for d in docs if d.extraction and d.extraction.doc_type == "receipt"}
                ),
                "line_items": sum(r["line_items"] for r in rows),
                "amount_before_tax": round(sum(r["amount_before_tax"] for r in rows), 2),
                "tax": round(sum(r["tax"] for r in rows), 2),
                "total": round(sum(r["total"] for r in rows), 2),
            }
        )
    return rows


def _csv(columns: list[str], rows: list[dict[str, Any]], *, bom: bool) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _csv_value(row.get(k)) for k in columns})
    text = buf.getvalue()
    # Excel needs a BOM to read UTF-8 CSV correctly; Google Sheets doesn't want one.
    return (("﻿" if bom else "") + text).encode("utf-8")


def _csv_value(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v - round(v, 2)) < 1e-9 else f"{v:g}"
    return safe_text(v)


def export_csv(docs: list[Document]) -> bytes:
    return _csv(document_columns(docs), [document_row(d) for d in docs], bom=True)


def export_csv_lines(docs: list[Document]) -> bytes:
    return _csv(line_columns(docs), line_rows(docs), bom=True)


def export_csv_categories(docs: list[Document]) -> bytes:
    return _csv(SUMMARY_COLUMNS, summary_with_total(docs), bom=True)


def export_sheets(docs: list[Document]) -> bytes:
    """Google Sheets import: UTF-8 without BOM, ISO dates, plain numbers, one row per line item.

    Documents without line items (forms, or invoices with none) get one row.
    """
    rows = line_rows(docs)
    with_lines = {r["file"] for r in rows}
    for d in docs:
        if d.filename not in with_lines:
            base = document_row(d)
            rows.append({k: base.get(k, "") for k in line_columns(docs)} | {"file": d.filename})
    columns = [*line_columns(docs), "subtotal", "total"]
    totals = {d.filename: document_row(d) for d in docs}
    for r in rows:
        r["subtotal"] = totals[r["file"]].get("subtotal")
        r["total"] = totals[r["file"]].get("total")
    return _csv(columns, rows, bom=False)


def export_json(docs: list[Document], batch_id: str) -> bytes:
    payload = {
        "batch_id": batch_id,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": [
            {
                "id": d.id,
                "file": d.filename,
                "type": d.doc_type,
                "status": d.status,
                "provider": d.provider,
                "extraction": d.extraction.model_dump() if d.extraction else None,
                "checks": [c.model_dump() for c in d.checks],
            }
            for d in docs
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


# ---- Excel ----

HEADER_FILL = PatternFill("solid", fgColor="0F766E")
HEADER_FONT = Font(bold=True, color="FFFFFF")
MONEY_COLS = {
    "subtotal",
    "gst",
    "hst",
    "pst",
    "qst",
    "other_tax",
    "tip",
    "total",
    "unit_price",
    "amount",
    "amount_before_tax",
    "tax",
}
DATE_COLS = {"date", "due_date"}


_ACRONYMS = {"gst": "GST", "hst": "HST", "pst": "PST", "qst": "QST", "line_items": "Line items"}


def _header(column: str) -> str:
    return _ACRONYMS.get(column, column.replace("_", " ").capitalize())


def _sheet(
    wb: Workbook, title: str, columns: list[str], rows: list[dict[str, Any]], first: bool
) -> None:
    ws = wb.active if first else wb.create_sheet()
    assert ws is not None
    ws.title = title
    ws.append([_header(c) for c in columns])
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        values = []
        for c in columns:
            v = row.get(c)
            if c in DATE_COLS and isinstance(v, str) and v:
                parsed = parse_date(v)
                v = parsed if parsed else v
            values.append(safe_text(v) if v is not None else None)
        ws.append(values)
    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        width = max([len(str(col))] + [len(str(r.get(col) or "")) for r in rows[:500]]) + 2
        ws.column_dimensions[letter].width = min(max(width, 8), 48)
        for cell in ws[letter][1:]:
            if col in MONEY_COLS:
                cell.number_format = "#,##0.00"
            elif isinstance(cell.value, date):
                cell.number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions


def export_xlsx(docs: list[Document]) -> bytes:
    wb = Workbook()
    _sheet(wb, "Documents", document_columns(docs), [document_row(d) for d in docs], first=True)
    _sheet(wb, "Line items", line_columns(docs), line_rows(docs), first=False)
    tax_rows = [
        {"file": d.filename, "kind": t.kind, "rate": t.rate, "amount": t.amount}
        for d in docs
        if d.extraction
        for t in d.extraction.taxes
    ]
    _sheet(wb, "Taxes", ["file", "kind", "rate", "amount"], tax_rows, first=False)
    check_rows = [
        {"file": d.filename, "check": c.label, "result": c.status, "details": c.message}
        for d in docs
        for c in d.checks
    ]
    _sheet(wb, "Checks", ["file", "check", "result", "details"], check_rows, first=False)
    summary = summary_with_total(docs)
    if summary:
        _sheet(wb, "By category", SUMMARY_COLUMNS, summary, first=False)
        ws = wb["By category"]
        ws.cell(row=len(summary) + 3, column=1, value=DISCLAIMER).font = Font(italic=True)
        for cell in ws[len(summary) + 1]:
            cell.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export(fmt: ExportFormat, docs: list[Document], batch_id: str) -> bytes:
    if fmt == "csv":
        return export_csv(docs)
    if fmt == "csv-lines":
        return export_csv_lines(docs)
    if fmt == "csv-categories":
        return export_csv_categories(docs)
    if fmt == "sheets":
        return export_sheets(docs)
    if fmt == "xlsx":
        return export_xlsx(docs)
    return export_json(docs, batch_id)
