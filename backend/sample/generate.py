"""Generate the sample documents and their ground truth.

Every business here is fictional. The documents tell one small story: the paperwork that lands on
the desk of "Juniper Lane Bakery", a made-up bakery in Guelph, Ontario, in one month.

Run from backend/:  uv run python sample/generate.py

Writes, next to this file:
  documents/*.pdf|png|jpg   the sample documents
  truth/*.json              ground truth for each document (values, sources, expected checks)
  manifest.json             file list, SHA-256 hashes, titles, and the sample batch's custom fields
"""

import hashlib
import io
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.pages import QuoteLocator  # noqa: E402

DOCS = HERE / "documents"
TRUTH = HERE / "truth"

CLIENT = ["Juniper Lane Bakery Inc.", "412 Juniper Lane", "Guelph, ON N1H 2K7"]
CENT = Decimal("0.01")
FIXED_DATE = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def new_pdf(**kwargs: Any) -> FPDF:
    pdf = FPDF(**kwargs)
    pdf.set_creation_date(FIXED_DATE)
    pdf.set_creator("paperwork-ai sample generator")
    return pdf


def money(x: Decimal) -> str:
    return f"{x:,.2f}"


def q2(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


def D(x: Any) -> Decimal:
    return Decimal(str(x))


def num(x: Decimal) -> float:
    return float(x)


@dataclass
class Line:
    description: str
    qty: Decimal
    unit: Decimal
    amount_override: Decimal | None = None

    @property
    def amount(self) -> Decimal:
        return (
            self.amount_override if self.amount_override is not None else q2(self.qty * self.unit)
        )


@dataclass
class Tax:
    kind: str
    rate: Decimal  # percent
    base: Decimal | None = None  # defaults to the subtotal


@dataclass
class Vendor:
    name: str
    address: list[str]
    tax_label: str | None = None
    tax_number: str | None = None
    contact: str = ""


@dataclass
class InvoiceSpec:
    stem: str
    title: str
    scenario: str
    vendor: Vendor
    number: str
    issued: date
    due: date | None
    date_fmt: str  # strftime pattern used on the page
    currency: str
    lines: list[Line]
    taxes: list[Tax]
    style: str = "modern"
    accent: tuple[int, int, int] = (30, 64, 96)
    currency_note: str | None = None  # e.g. "All amounts in CAD"
    total_label: str | None = None
    subtotal_delta: Decimal = Decimal(0)  # printed subtotal minus the true sum (a document error)
    total_delta: Decimal = Decimal(0)
    stamp: str | None = None
    terms: str = "Net 30"
    notes: str = "Thank you for your business."
    lines_first_page: int = 99
    expected_checks: list[str] = field(default_factory=list)


class Recorder:
    """Collects ground truth while a document is drawn, so values and quotes always match."""

    def __init__(self, doc_type: str) -> None:
        self.doc_type = doc_type
        self.fields: dict[str, dict[str, Any]] = {}
        self.line_items: list[dict[str, Any]] = []
        self.taxes: list[dict[str, Any]] = []

    def field(self, key: str, value: Any, quote: str, page: int = 1) -> None:
        self.fields[key] = {"value": value, "page": page, "quote": quote}

    def missing(self, key: str) -> None:
        self.fields[key] = {"value": None, "page": None, "quote": None}

    def line(self, ln: Line, quote: str, page: int) -> None:
        self.line_items.append(
            {
                "description": ln.description,
                "quantity": num(ln.qty),
                "unit_price": num(ln.unit),
                "amount": num(ln.amount),
                "page": page,
                "quote": quote,
            }
        )

    def tax(self, kind: str, rate: Decimal | None, amount: Decimal, quote: str, page: int) -> None:
        self.taxes.append(
            {
                "kind": kind,
                "rate": num(rate) if rate is not None else None,
                "amount": num(amount),
                "page": page,
                "quote": quote,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {"fields": self.fields, "line_items": self.line_items, "taxes": self.taxes}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


def fmt_date(d: date, pattern: str) -> str:
    # Portable day without a leading zero.
    return d.strftime(pattern.replace("%-d", str(d.day)))


class InvoicePDF(FPDF):
    def __init__(self, spec: InvoiceSpec) -> None:
        super().__init__(unit="mm", format="Letter")
        self.set_creation_date(FIXED_DATE)
        self.set_creator("paperwork-ai sample generator")
        self.spec = spec
        self.set_auto_page_break(False)
        self.set_margins(18, 16, 18)
        self.base_font = {"modern": "Helvetica", "classic": "Times", "mono": "Courier"}[spec.style]

    def font(self, size: float, bold: bool = False) -> None:
        self.set_font(self.base_font, "B" if bold else "", size)


def render_invoice(spec: InvoiceSpec) -> tuple[bytes, dict[str, Any]]:
    rec = Recorder("invoice")
    pdf = InvoicePDF(spec)
    v = spec.vendor
    r, g, b = spec.accent
    true_subtotal = sum((ln.amount for ln in spec.lines), Decimal(0))
    subtotal = true_subtotal + spec.subtotal_delta
    tax_amounts = [
        q2((t.base if t.base is not None else subtotal) * t.rate / 100) for t in spec.taxes
    ]
    total = subtotal + sum(tax_amounts, Decimal(0)) + spec.total_delta

    pages = 1 if len(spec.lines) <= spec.lines_first_page else 2

    def header(page: int) -> float:
        pdf.add_page()
        if spec.style == "modern":
            pdf.set_fill_color(r, g, b)
            pdf.rect(0, 0, 216, 7, "F")
            pdf.set_xy(18, 16)
            pdf.font(19, True)
            pdf.set_text_color(r, g, b)
            pdf.cell(110, 9, v.name)
            pdf.set_text_color(40, 40, 40)
            pdf.set_xy(140, 16)
            pdf.font(22, True)
            pdf.cell(58, 9, "INVOICE", align="R")
        elif spec.style == "classic":
            pdf.set_xy(18, 16)
            pdf.font(21, True)
            pdf.set_text_color(25, 25, 25)
            pdf.cell(180, 9, v.name, align="C")
            pdf.set_draw_color(r, g, b)
            pdf.set_line_width(0.6)
            pdf.line(18, 27, 198, 27)
            pdf.set_line_width(0.2)
        else:
            pdf.set_xy(18, 16)
            pdf.font(15, True)
            pdf.set_text_color(20, 20, 20)
            pdf.cell(180, 8, v.name.upper())
        if page == 1:
            rec.field("vendor_name", v.name, v.name if spec.style != "mono" else v.name.upper())
        pdf.set_text_color(70, 70, 70)
        pdf.font(9)
        y = 27 if spec.style != "classic" else 30
        lines = [*v.address]
        if v.tax_number:
            lines.append(f"{v.tax_label} {v.tax_number}")
        if v.contact:
            lines.append(v.contact)
        align = "C" if spec.style == "classic" else "L"
        for i, text in enumerate(lines):
            pdf.set_xy(18, y + i * 4.6)
            pdf.cell(180 if align == "C" else 100, 4.6, text, align=align)
        if page == 1:
            rec.field("vendor_address", ", ".join(v.address), v.address[0])
            if v.tax_number:
                rec.field("vendor_tax_number", v.tax_number, f"{v.tax_label} {v.tax_number}")
            else:
                rec.missing("vendor_tax_number")
        if pages > 1:
            pdf.font(8)
            pdf.set_xy(140, 262)
            pdf.cell(58, 5, f"Page {page} of {pages}", align="R")
        return y + len(lines) * 4.6 + 6

    y = header(1)

    # Meta block and bill-to.
    pdf.set_text_color(30, 30, 30)
    meta: list[tuple[str, str]] = [
        ("Invoice #", spec.number),
        ("Date", fmt_date(spec.issued, spec.date_fmt)),
    ]
    if spec.due:
        meta.append(("Due date", fmt_date(spec.due, spec.date_fmt)))
    meta.append(("Terms", spec.terms))
    if spec.style == "classic":
        meta = [("Invoice No.", spec.number), *meta[1:]]
    if spec.style == "mono":
        meta = [("INVOICE NO", spec.number), *[(k.upper(), val) for k, val in meta[1:]]]
    my = y
    for label, val in meta:
        pdf.set_xy(122, my)
        pdf.font(9.5, True)
        pdf.cell(30, 5.5, label)
        pdf.font(9.5)
        pdf.cell(46, 5.5, val, align="R")
        my += 5.5
    label0 = meta[0][0]
    rec.field("invoice_number", spec.number, f"{label0} {spec.number}")
    rec.field("invoice_date", spec.issued.isoformat(), fmt_date(spec.issued, spec.date_fmt))
    if spec.due:
        rec.field("due_date", spec.due.isoformat(), fmt_date(spec.due, spec.date_fmt))
    else:
        rec.missing("due_date")

    pdf.set_xy(18, y)
    pdf.font(8.5, True)
    pdf.set_text_color(r, g, b)
    pdf.cell(80, 5, "BILL TO" if spec.style != "classic" else "Billed to")
    pdf.set_text_color(30, 30, 30)
    for i, text in enumerate(CLIENT):
        pdf.set_xy(18, y + 5.5 + i * 4.8)
        pdf.font(9.5, i == 0)
        pdf.cell(90, 4.8, text)
    rec.field("bill_to", CLIENT[0], CLIENT[0])

    y = max(my, y + 5.5 + 3 * 4.8) + 6
    if spec.currency_note:
        pdf.set_xy(18, y)
        pdf.font(8.5)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(180, 4.5, spec.currency_note)
        y += 7
        pdf.set_text_color(30, 30, 30)

    # Line items table.
    cols = [
        (92, "Description", "L"),
        (18, "Qty", "R"),
        (32, "Unit price", "R"),
        (38, "Amount", "R"),
    ]

    def table_header(y: float) -> float:
        pdf.set_xy(18, y)
        pdf.font(9, True)
        if spec.style == "modern":
            pdf.set_fill_color(r, g, b)
            pdf.set_text_color(255, 255, 255)
            for w, label, align in cols:
                pdf.cell(w, 7, label, align=align, fill=True)
        else:
            pdf.set_text_color(30, 30, 30)
            for w, label, align in cols:
                pdf.cell(w, 7, label.upper() if spec.style == "mono" else label, align=align)
            pdf.set_draw_color(120, 120, 120)
            pdf.line(18, y + 7, 198, y + 7)
        pdf.set_text_color(30, 30, 30)
        return y + 8

    y = table_header(y)
    page = 1
    for i, ln in enumerate(spec.lines):
        if i == spec.lines_first_page:
            pdf.set_xy(18, y + 2)
            pdf.font(8.5)
            pdf.set_text_color(90, 90, 90)
            pdf.cell(180, 5, "Continued on next page", align="R")
            page = 2
            y = header(2)
            pdf.set_xy(18, y)
            pdf.font(10, True)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(180, 6, f"Invoice {spec.number} (continued)")
            y = table_header(y + 9)
        pdf.font(9.5)
        if spec.style == "modern" and i % 2 == 1:
            pdf.set_fill_color(244, 246, 248)
            pdf.rect(18, y, 180, 6.4, "F")
        pdf.set_xy(18, y)
        qty = f"{ln.qty.normalize():f}"
        pdf.cell(cols[0][0], 6.4, ln.description)
        pdf.cell(cols[1][0], 6.4, qty, align="R")
        pdf.cell(cols[2][0], 6.4, money(ln.unit), align="R")
        pdf.cell(cols[3][0], 6.4, money(ln.amount), align="R")
        rec.line(ln, ln.description, page)
        y += 6.4

    pdf.set_draw_color(150, 150, 150)
    pdf.line(18, y + 1, 198, y + 1)
    y += 4

    def total_row(label: str, amount: Decimal, bold: bool = False) -> str:
        nonlocal y
        pdf.set_xy(110, y)
        pdf.font(10 if not bold else 11, bold)
        pdf.cell(50, 6.5, label, align="R")
        pdf.cell(38, 6.5, money(amount), align="R")
        y += 6.5
        return f"{label} {money(amount)}"

    sub_label = "Subtotal" if spec.style != "mono" else "SUBTOTAL"
    rec.field("subtotal", num(subtotal), total_row(sub_label, subtotal), page)
    for t, amt in zip(spec.taxes, tax_amounts, strict=True):
        rate = f"{t.rate.normalize():f}"
        label = f"{t.kind} ({rate}%)"
        if t.base is not None and t.base != subtotal:
            label = f"{t.kind} ({rate}% on {money(t.base)})"
        rec.tax(t.kind, t.rate, amt, total_row(label, amt), page)
    if spec.style == "modern":
        pdf.set_fill_color(r, g, b)
        pdf.rect(110, y + 1, 88, 0.6, "F")
        y += 2.5
    total_label = spec.total_label or f"Total ({spec.currency})"
    rec.field("total", num(total), total_row(total_label, total, bold=True), page)

    # Currency source: the currency note if printed, else the total label.
    if spec.currency_note and spec.currency in spec.currency_note:
        rec.field("currency", spec.currency, spec.currency_note)
    else:
        rec.field("currency", spec.currency, f"{total_label} {money(total)}", page)

    y += 8
    pdf.set_xy(18, y)
    pdf.font(9)
    pdf.set_text_color(80, 80, 80)
    pdf.multi_cell(120, 4.6, spec.notes)

    if spec.stamp:
        pdf.set_text_color(185, 40, 40)
        pdf.set_draw_color(185, 40, 40)
        pdf.set_line_width(0.8)
        pdf.page = 1
        with pdf.rotation(8, 160, 168):
            pdf.rect(124, 160, 70, 15)
            pdf.set_xy(124, 163.5)
            pdf.font(15, True)
            pdf.cell(70, 8, spec.stamp, align="C")
        pdf.set_line_width(0.2)

    truth = rec.as_dict()
    truth["page_count"] = pages
    return bytes(pdf.output()), truth


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass
class ReceiptSpec:
    stem: str
    title: str
    scenario: str
    merchant: str
    address: list[str]
    tax_line: str
    when: str  # as printed
    iso_date: str
    lines: list[tuple[Line, bool]]  # (line, taxable)
    tax_kind: str
    tax_rate: Decimal
    payment: str
    payment_quote: str
    tip: Decimal | None = None
    width_mm: float = 80
    expected_checks: list[str] = field(default_factory=list)


def render_receipt(spec: ReceiptSpec) -> tuple[bytes, dict[str, Any]]:
    rec = Recorder("receipt")
    subtotal = sum((ln.amount for ln, _ in spec.lines), Decimal(0))
    taxable = sum((ln.amount for ln, t in spec.lines if t), Decimal(0))
    tax = q2(taxable * spec.tax_rate / 100)
    tip = spec.tip or Decimal(0)
    total = subtotal + tax + tip
    height = 84 + len(spec.lines) * 8.4 + (5 if spec.tip else 0)
    pdf = new_pdf(unit="mm", format=(spec.width_mm, height))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    w = spec.width_mm - 10
    pdf.set_text_color(20, 20, 20)

    def row(
        text: str, size: float = 8.5, bold: bool = False, align: str = "C", h: float = 4.2
    ) -> None:
        pdf.set_x(5)
        pdf.set_font("Courier", "B" if bold else "", size)
        pdf.cell(w, h, text, align=align, new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(8)
    row(spec.merchant.upper(), 11, True, h=6)
    rec.field("merchant_name", spec.merchant, spec.merchant.upper())
    for a in spec.address:
        row(a)
    rec.field("merchant_address", ", ".join(spec.address), spec.address[0])
    row(spec.tax_line)
    pdf.ln(2)
    row(spec.when)
    rec.field("date", spec.iso_date, spec.when)
    row("-" * 32)

    def two(left: str, right: str, bold: bool = False) -> str:
        pdf.set_x(5)
        pdf.set_font("Courier", "B" if bold else "", 8.5)
        pdf.cell(w - 22, 4.4, left)
        pdf.cell(22, 4.4, right, align="R", new_x="LMARGIN", new_y="NEXT")
        return f"{left} {right}"

    for ln, taxable_line in spec.lines:
        flag = " H" if taxable_line and spec.tax_kind == "HST" and len(spec.lines) > 4 else ""
        two(ln.description, money(ln.amount) + flag)
        rec.line(ln, ln.description, 1)
        if ln.qty != 1:
            pdf.set_x(9)
            pdf.set_font("Courier", "", 7.5)
            pdf.cell(
                w - 4,
                3.8,
                f"{ln.qty.normalize():f} @ {money(ln.unit)}",
                new_x="LMARGIN",
                new_y="NEXT",
            )
    row("-" * 32)
    rec.field("subtotal", num(subtotal), two("SUBTOTAL", money(subtotal)))
    rate = f"{spec.tax_rate.normalize():f}"
    if taxable != subtotal:
        label = f"{spec.tax_kind} {rate}% ON {money(taxable)}"
    else:
        label = f"{spec.tax_kind} {rate}%"
    rec.tax(spec.tax_kind, spec.tax_rate, tax, two(label, money(tax)), 1)
    if spec.tip:
        rec.field("tip", num(tip), two("TIP", money(tip)))
    else:
        rec.missing("tip")
    rec.field("total", num(total), two("TOTAL", money(total), bold=True))
    rec.field("currency", "CAD", "ALL PRICES IN CAD")
    pdf.ln(2)
    row(spec.payment_quote)
    rec.field("payment_method", spec.payment, spec.payment_quote)
    auth = int(hashlib.sha256(spec.stem.encode()).hexdigest()[:6], 16) % 90000 + 10000
    row(f"APPROVED  AUTH 0{auth}")
    pdf.ln(2)
    row("ALL PRICES IN CAD", 7.5)
    row("THANK YOU FOR SHOPPING LOCAL", 7.5)
    truth = rec.as_dict()
    truth["page_count"] = 1
    return bytes(pdf.output()), truth


# ---------------------------------------------------------------------------
# A filled-in form (custom fields)
# ---------------------------------------------------------------------------

FORM_FIELDS = [
    {
        "key": "customer_name",
        "label": "Customer name",
        "type": "text",
        "required": True,
        "description": "The person placing the order.",
    },
    {
        "key": "phone",
        "label": "Phone",
        "type": "text",
        "required": True,
        "description": "Contact phone number.",
    },
    {
        "key": "email",
        "label": "Email",
        "type": "email",
        "required": False,
        "description": "Contact email address.",
    },
    {
        "key": "event_date",
        "label": "Event date",
        "type": "date",
        "required": True,
        "description": "The date the order is needed.",
    },
    {
        "key": "fulfilment",
        "label": "Pickup or delivery",
        "type": "text",
        "required": False,
        "description": "Whether the customer picks up or wants delivery.",
    },
    {
        "key": "guest_count",
        "label": "Guests",
        "type": "number",
        "required": False,
        "description": "Number of guests.",
    },
    {
        "key": "order_details",
        "label": "Order details",
        "type": "text",
        "required": True,
        "description": "What the customer is ordering, in one line.",
    },
    {
        "key": "budget",
        "label": "Budget",
        "type": "money",
        "required": False,
        "description": "The customer's budget, as a number.",
    },
]


def render_form() -> tuple[bytes, dict[str, Any]]:
    rec = Recorder("custom")
    pdf = new_pdf(unit="mm", format="Letter")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    teal = (122, 74, 46)
    pdf.set_fill_color(*teal)
    pdf.rect(0, 0, 216, 30, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(18, 8)
    pdf.set_font("Times", "B", 20)
    pdf.cell(180, 9, "Juniper Lane Bakery")
    pdf.set_xy(18, 18)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(
        180, 6, "Catering order request  |  412 Juniper Lane, Guelph  |  orders@juniperlane.example"
    )
    pdf.set_text_color(40, 40, 40)
    entries = [
        ("customer_name", "Customer name", "Priya Raman", "Priya Raman"),
        ("phone", "Phone", "(519) 555-0148", "(519) 555-0148"),
        ("email", "Email", "priya.raman@example.com", "priya.raman@example.com"),
        ("event_date", "Event date", "Sat. Nov 21, 2026", "2026-11-21"),
        (
            "fulfilment",
            "Pickup or delivery",
            "Delivery to Riverside Community Hall, 75 Water St",
            "Delivery",
        ),
        ("guest_count", "Number of guests", "60", 60.0),
        (
            "order_details",
            "Order details",
            "3 dozen croissants, 2 dozen scones, 1 large carrot cake",
            None,
        ),
        ("budget", "Budget", "$450", 450.0),
    ]
    y = 44
    for key, label, written, value in entries:
        pdf.set_xy(18, y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(180, 5, label.upper())
        pdf.set_draw_color(180, 180, 180)
        pdf.rect(18, y + 6, 180, 11)
        pdf.set_xy(21, y + 8)
        pdf.set_font("Courier", "B", 12)
        pdf.set_text_color(20, 40, 110)
        pdf.cell(174, 7, written)
        if value is None:
            value = written
        rec.field(key, value, written)
        y += 22
    pdf.set_xy(18, y + 4)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(
        180,
        4.5,
        "We confirm every catering order by phone within one business day. A 25% deposit holds your "
        "date. Office use: entered by ____  confirmed ____",
    )
    truth = rec.as_dict()
    truth["page_count"] = 1
    return bytes(pdf.output()), truth


# ---------------------------------------------------------------------------
# Making PDFs look scanned or photographed
# ---------------------------------------------------------------------------


def render_page(pdf_bytes: bytes, dpi: int) -> Image.Image:
    doc = pdfium.PdfDocument(pdf_bytes)
    img = doc[0].render(scale=dpi / 72).to_pil().convert("RGB")
    doc.close()
    return img


def boxes_for(pdf_bytes: bytes, truth: dict[str, Any]) -> list[tuple[dict[str, Any], list]]:
    """Normalized boxes for every quote in the truth, from the source PDF's text layer."""
    out = []
    with QuoteLocator(pdf_bytes) as loc:
        items = [*truth["fields"].values(), *truth["line_items"], *truth["taxes"]]
        for item in items:
            if not item.get("quote"):
                continue
            boxes = loc.find(item["page"], item["quote"]) or []
            out.append((item, [[b.x0, b.y0, b.x1, b.y1] for b in boxes]))
    return out


def rotate_point(
    x: float, y: float, w: int, h: int, angle: float, nw: int, nh: int
) -> tuple[float, float]:
    """Where pixel (x, y) lands after PIL's rotate(angle, expand=True) (counter-clockwise)."""
    t = math.radians(angle)
    dx, dy = x - w / 2, y - h / 2
    return (
        nw / 2 + dx * math.cos(t) + dy * math.sin(t),
        nh / 2 - dx * math.sin(t) + dy * math.cos(t),
    )


def transform_boxes(
    entries: list[tuple[dict[str, Any], list]],
    src_size: tuple[int, int],
    angle: float,
    rot_size: tuple[int, int],
    offset: tuple[int, int],
    final_size: tuple[int, int],
) -> None:
    w, h = src_size
    nw, nh = rot_size
    fw, fh = final_size
    for item, boxes in entries:
        out = []
        for x0, y0, x1, y1 in boxes:
            pts = [
                rotate_point(px * w, py * h, w, h, angle, nw, nh)
                for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
            ]
            xs = [p[0] + offset[0] for p in pts]
            ys = [p[1] + offset[1] for p in pts]
            out.append(
                {
                    "x0": round(min(xs) / fw, 4),
                    "y0": round(min(ys) / fh, 4),
                    "x1": round(max(xs) / fw, 4),
                    "y1": round(max(ys) / fh, 4),
                }
            )
        item["boxes"] = out


def add_noise(img: Image.Image, amount: int, seed: int) -> Image.Image:
    rnd = random.Random(seed)
    # Seeded noise, so regenerating gives byte-identical files.
    noise = Image.frombytes("L", img.size, rnd.randbytes(img.width * img.height))
    noise = Image.blend(Image.new("L", img.size, 128), noise, amount / 255)
    speckle = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(speckle)
    for _ in range(img.width * img.height // 2500):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        draw.point((x, y), fill=rnd.randrange(60, 160))
    base = img.convert("RGB")
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    out = Image.blend(base, noise_rgb, 0.08)
    dark = Image.new("RGB", img.size, (70, 70, 70))
    return Image.composite(dark, out, speckle)


def make_scan(pdf_bytes: bytes, truth: dict[str, Any]) -> bytes:
    entries = boxes_for(pdf_bytes, truth)
    page = render_page(pdf_bytes, 150)
    # Slightly grey, low-contrast paper, then a tilt as if fed crooked through a scanner.
    page = Image.blend(page, Image.new("RGB", page.size, (232, 229, 220)), 0.18)
    angle = 1.4
    rotated = page.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(214, 212, 205)
    )
    rotated = add_noise(rotated, 60, seed=6).filter(ImageFilter.GaussianBlur(0.6)).convert("L")
    transform_boxes(entries, page.size, angle, rotated.size, (0, 0), rotated.size)
    buf = io.BytesIO()
    rotated.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def make_photo(pdf_bytes: bytes, truth: dict[str, Any]) -> bytes:
    entries = boxes_for(pdf_bytes, truth)
    paper = render_page(pdf_bytes, 220)
    paper = Image.blend(paper, Image.new("RGB", paper.size, (246, 242, 230)), 0.25)
    angle = -3.2
    rotated = paper.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0)
    )
    mask = Image.new("L", paper.size, 255).rotate(angle, expand=True, fillcolor=0)
    # A plain counter top behind the receipt.
    bg_w, bg_h = rotated.width + 260, rotated.height + 220
    bg = Image.new("RGB", (bg_w, bg_h), (92, 74, 58))
    bg = add_noise(bg, 40, seed=7)
    offset = (130, 95)
    bg.paste(rotated, offset, mask)
    # Uneven light from one side, then camera softness.
    light = Image.linear_gradient("L").rotate(90).resize((bg_w, bg_h))
    bg = Image.composite(bg, Image.blend(bg, Image.new("RGB", bg.size, (30, 26, 22)), 0.25), light)
    bg = bg.filter(ImageFilter.GaussianBlur(0.8))
    transform_boxes(entries, paper.size, angle, rotated.size, offset, (bg_w, bg_h))
    bg.thumbnail((1400, 2400))
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=82)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# The sample set
# ---------------------------------------------------------------------------

NORTHPEAK = Vendor(
    "Northpeak Office Supply Ltd.",
    ["88 Wellington St W, Suite 400", "Toronto, ON M5J 1H1"],
    "HST No.",
    "81234 5678 RT0001",
    "billing@northpeak.example  |  (416) 555-0193",
)


def northpeak(
    stem: str, title: str, scenario: str, stamp: str | None, checks: list[str]
) -> InvoiceSpec:
    return InvoiceSpec(
        stem=stem,
        title=title,
        scenario=scenario,
        vendor=NORTHPEAK,
        number="NP-24817",
        issued=date(2026, 9, 14),
        due=date(2026, 10, 14),
        date_fmt="%b %-d, %Y",
        currency="CAD",
        lines=[
            Line("Receipt printer paper rolls (case of 50)", D(2), D("64.50")),
            Line("Laser toner cartridge, black", D(3), D("89.99")),
            Line("Label maker tape, 12 mm", D(6), D("14.25")),
            Line("Ergonomic counter stool", D(2), D("189.00")),
            Line("Delivery, Guelph", D(1), D("35.00")),
        ],
        taxes=[Tax("HST", D(13))],
        style="modern",
        accent=(18, 94, 89),
        stamp=stamp,
        expected_checks=checks,
    )


INVOICES: list[InvoiceSpec] = [
    northpeak(
        "01-northpeak-office-supply",
        "Office supplies (HST)",
        "A clean Ontario invoice with 13% HST.",
        None,
        [],
    ),
    InvoiceSpec(
        stem="02-cedar-pine-packaging",
        title="Packaging (GST + PST)",
        scenario="A British Columbia supplier charging 5% GST and 7% PST.",
        vendor=Vendor(
            "Cedar & Pine Packaging Co.",
            ["1270 Industrial Ave", "Vancouver, BC V6A 2N4"],
            "GST Reg.",
            "76543 2109 RT0001",
            "accounts@cedarpine.example",
        ),
        number="CP-1093",
        issued=date(2026, 9, 18),
        due=date(2026, 10, 18),
        date_fmt="%B %-d, %Y",
        currency="CAD",
        currency_note="All amounts in Canadian dollars (CAD)",
        lines=[
            Line("Kraft bakery boxes 10x10x5 (bundle of 100)", D(4), D("58.00")),
            Line("Window cupcake inserts (pack of 200)", D(2), D("31.40")),
            Line("Compostable paper bags, medium (case)", D(3), D("42.75")),
            Line("Custom logo stickers, 1,000 count", D(1), D("118.00")),
        ],
        taxes=[Tax("GST", D(5)), Tax("PST", D(7))],
        style="classic",
        accent=(120, 82, 40),
    ),
    InvoiceSpec(
        stem="03-maple-ridge-flour-mill",
        title="Ingredients, two pages (GST)",
        scenario="A long Alberta invoice that runs onto a second page.",
        vendor=Vendor(
            "Maple Ridge Flour Mill",
            ["4410 Mill Road SE", "Calgary, AB T2C 4N9"],
            "GST #",
            "70011 4482 RT0001",
            "orders@mapleridgemill.example  |  (403) 555-0177",
        ),
        number="MR-58210",
        issued=date(2026, 9, 21),
        due=date(2026, 10, 21),
        date_fmt="%Y-%m-%d",
        currency="CAD",
        lines=[
            Line(desc, D(q), D(p))
            for desc, q, p in [
                ("Unbleached bread flour, 20 kg", 12, "31.80"),
                ("All-purpose flour, 20 kg", 8, "27.40"),
                ("Whole wheat flour, 20 kg", 6, "29.95"),
                ("Dark rye flour, 10 kg", 3, "24.10"),
                ("Spelt flour, 10 kg", 2, "33.60"),
                ("Pastry flour, 20 kg", 5, "30.25"),
                ("Semolina, 10 kg", 2, "21.90"),
                ("Rolled oats, 10 kg", 3, "18.75"),
                ("Cane sugar, 20 kg", 6, "36.40"),
                ("Brown sugar, 10 kg", 4, "22.80"),
                ("Icing sugar, 10 kg", 3, "19.60"),
                ("Sea salt, fine, 5 kg", 2, "11.30"),
                ("Instant dry yeast, 500 g", 10, "6.95"),
                ("Baking powder, 2 kg", 3, "14.20"),
                ("Baking soda, 2 kg", 2, "7.45"),
                ("Vanilla extract, 1 L", 2, "42.00"),
                ("Cocoa powder, 5 kg", 2, "48.90"),
                ("Dark chocolate callets, 5 kg", 4, "79.50"),
                ("Cinnamon, ground, 1 kg", 2, "17.60"),
                ("Raisins, 5 kg", 2, "28.30"),
                ("Walnut pieces, 2 kg", 3, "34.20"),
                ("Sunflower seeds, 5 kg", 1, "21.40"),
                ("Poppy seeds, 1 kg", 2, "12.90"),
                ("Sesame seeds, 2 kg", 2, "15.80"),
                ("Malt syrup, 3 kg", 1, "26.70"),
                ("Canola oil, 16 L", 2, "54.60"),
                ("Parchment sheets, full size (1,000)", 1, "62.00"),
                ("Fuel surcharge", 1, "18.00"),
            ]
        ],
        taxes=[Tax("GST", D(5))],
        style="modern",
        accent=(146, 64, 14),
        lines_first_page=22,
    ),
    InvoiceSpec(
        stem="04-bluewater-print-shop",
        title="Printing, line items don't add up",
        scenario="The printed subtotal is 40.00 more than the line items. A real document error.",
        vendor=Vendor(
            "Bluewater Print Shop",
            ["2215 Gottingen St", "Halifax, NS B3K 3B5"],
            "HST Reg. No.",
            "88990 1122 RT0001",
            "hello@bluewaterprint.example",
        ),
        number="BW-7731",
        issued=date(2026, 9, 24),
        due=date(2026, 10, 9),
        date_fmt="%d/%m/%Y",
        currency="CAD",
        terms="Net 15",
        lines=[
            Line("Menu boards, 24x36 foam core", D(3), D("46.00")),
            Line("Tri-fold brochures (500)", D(1), D("185.00")),
            Line("Business cards, matte (1,000)", D(2), D("52.50")),
            Line("Window decal, cut vinyl", D(1), D("96.00")),
        ],
        taxes=[Tax("HST", D(15))],
        style="mono",
        subtotal_delta=D("40.00"),
        expected_checks=["line_items_sum"],
    ),
    northpeak(
        "05-northpeak-office-supply-resent",
        "Office supplies, sent twice",
        "The same Northpeak invoice, re-sent with a 'COPY' stamp. A duplicate.",
        "COPY - RESENT",
        ["duplicate"],
    ),
    InvoiceSpec(
        stem="06-lakeshore-cleaning-scan",
        title="Cleaning, scanned and tilted",
        scenario="A paper invoice scanned crooked, with noise. Demo mode misreads one amount, "
        "the way a model can on a poor scan, and the checks catch it.",
        vendor=Vendor(
            "Lakeshore Commercial Cleaning",
            ["57 Ontario St", "Kingston, ON K7L 2Y2"],
            "HST#",
            "79912 3348 RT0001",
            "(613) 555-0122",
        ),
        number="LCC-2026-0912",
        issued=date(2026, 9, 30),
        due=date(2026, 10, 30),
        date_fmt="%b %-d, %Y",
        currency="CAD",
        lines=[
            Line("Deep clean, kitchen and prep area", D(1), D("420.00")),
            Line("Weekly front-of-house cleaning", D(4), D("135.00")),
            Line("Oven and hood degreasing", D(4), D("320.00")),
            Line("Floor strip and wax", D(1), D("260.00")),
        ],
        taxes=[Tax("HST", D(13))],
        style="classic",
        accent=(40, 60, 90),
    ),
    InvoiceSpec(
        stem="09-summit-cloud-hosting",
        title="Software, currency mix-up",
        scenario="A US vendor billing in USD whose total line says CAD. The currency check flags it.",
        vendor=Vendor(
            "Summit Cloud Hosting Inc.",
            ["900 SW Alder St, Floor 6", "Portland, OR 97205, USA"],
            None,
            None,
            "billing@summitcloud.example",
        ),
        number="SCH-INV-004417",
        issued=date(2026, 10, 1),
        due=date(2026, 10, 31),
        date_fmt="%m/%d/%Y",
        currency="USD",
        currency_note="Currency: USD",
        total_label="Total due (CAD)",
        lines=[
            Line("Online ordering site, Standard plan (October)", D(1), D("39.00")),
            Line("Point-of-sale sync add-on", D(1), D("12.00")),
            Line("Extra staff seats", D(3), D("4.00")),
        ],
        taxes=[],
        style="modern",
        accent=(55, 65, 160),
        terms="Due on receipt",
        expected_checks=["currency"],
    ),
    InvoiceSpec(
        stem="10-atelier-lumiere-design",
        title="Design (GST + QST)",
        scenario="A Quebec studio charging 5% GST and 9.975% QST, with a written-out date.",
        vendor=Vendor(
            "Atelier Lumière Design",
            ["5120 boul. Saint-Laurent", "Montréal, QC H2T 1R8"],
            "GST/QST:",
            "74422 9081 RT0001 / 1229384756 TQ0001",
            "studio@atelierlumiere.example",
        ),
        number="AL-2026-118",
        issued=date(2026, 10, 6),
        due=date(2026, 11, 5),
        date_fmt="%-d %B %Y",
        currency="CAD",
        currency_note="Amounts in CAD",
        lines=[
            Line("Seasonal menu design (holiday)", D(1), D("650.00")),
            Line("Social media templates, set of 12", D(1), D("280.00")),
            Line("Revisions (hourly)", D("2.5"), D("85.00")),
        ],
        taxes=[Tax("GST", D(5)), Tax("QST", D("9.975"))],
        style="classic",
        accent=(90, 40, 110),
    ),
    InvoiceSpec(
        stem="11-riverbend-courier",
        title="Courier, total doesn't add up",
        scenario="The printed total is 10.00 more than subtotal plus HST. A real document error.",
        vendor=Vendor(
            "Riverbend Courier Services",
            ["310 Bank St", "Ottawa, ON K2P 1X7"],
            "HST",
            "77180 6612 RT0001",
            "dispatch@riverbendcourier.example",
        ),
        number="RC-40981",
        issued=date(2026, 10, 9),
        due=date(2026, 10, 23),
        date_fmt="%Y-%m-%d",
        currency="CAD",
        terms="Net 14",
        lines=[
            Line("Same-day delivery, Guelph to Kitchener", D(6), D("28.50")),
            Line("Cold-chain tote rental (weekly)", D(2), D("15.00")),
            Line("Weekend delivery surcharge", D(2), D("12.00")),
        ],
        taxes=[Tax("HST", D(13))],
        style="mono",
        total_delta=D("10.00"),
        expected_checks=["totals"],
    ),
]

RECEIPTS: list[ReceiptSpec] = [
    ReceiptSpec(
        stem="07-harbour-street-hardware-photo",
        title="Hardware receipt photo",
        scenario="A phone photo of a till receipt on a counter, tilted, with uneven light.",
        merchant="Harbour Street Hardware",
        address=["19 Harbour St", "Hamilton, ON L8L 1A3"],
        tax_line="HST# 80455 1290 RT0001",
        when="2026-10-03  14:27",
        iso_date="2026-10-03",
        lines=[
            (Line("SHELF BRACKET 10IN", D(4), D("6.49")), True),
            (Line("WOOD SCREWS #8 BOX", D(1), D("8.99")), True),
            (Line("DOOR SWEEP 36IN", D(1), D("17.49")), True),
            (Line("LED BULB A19 4PK", D(2), D("11.99")), True),
        ],
        tax_kind="HST",
        tax_rate=D(13),
        payment="Visa ending 4021",
        payment_quote="VISA ************4021",
    ),
    ReceiptSpec(
        stem="08-greenleaf-market-receipt",
        title="Grocery e-receipt (part taxable)",
        scenario="A PDF receipt where groceries are zero-rated and only two items carry HST.",
        merchant="Greenleaf Market",
        address=["230 Gordon St", "Guelph, ON N1G 1X8"],
        tax_line="HST# 71234 0098 RT0001",
        when="2026-10-12  08:05",
        iso_date="2026-10-12",
        lines=[
            (Line("ORGANIC EGGS 30CT", D(2), D("11.49")), False),
            (Line("UNSALTED BUTTER 454G", D(4), D("6.29")), False),
            (Line("WHOLE MILK 4L", D(2), D("6.79")), False),
            (Line("LEMONS BAG 1KG", D(1), D("4.99")), False),
            (Line("PARCHMENT ROLL 30M", D(1), D("7.49")), True),
            (Line("DISH SOAP 1L", D(1), D("3.99")), True),
        ],
        tax_kind="HST",
        tax_rate=D(13),
        payment="Debit",
        payment_quote="INTERAC DEBIT ****8812",
        width_mm=86,
    ),
]


def write(
    stem: str, ext: str, data: bytes, truth: dict[str, Any], meta: dict[str, Any]
) -> dict[str, Any]:
    name = f"{stem}.{ext}"
    (DOCS / name).write_bytes(data)
    media = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}[ext]
    record = {
        "file": name,
        "media_type": media,
        "sha256": hashlib.sha256(data).hexdigest(),
        **meta,
    }
    (TRUTH / f"{stem}.json").write_text(
        json.dumps({**record, **truth}, indent=2, ensure_ascii=False) + "\n"
    )
    return record


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    TRUTH.mkdir(exist_ok=True)
    for old in [*DOCS.iterdir(), *TRUTH.iterdir()]:
        old.unlink()
    records = []

    for spec in INVOICES:
        data, truth = render_invoice(spec)
        meta = {
            "doc_type": "invoice",
            "title": spec.title,
            "scenario": spec.scenario,
            "expected_checks": spec.expected_checks,
        }
        if spec.stem.endswith("-scan"):
            png = make_scan(data, truth)
            records.append(write(spec.stem, "png", png, truth, meta))
        else:
            records.append(write(spec.stem, "pdf", data, truth, meta))

    for spec in RECEIPTS:
        data, truth = render_receipt(spec)
        meta = {
            "doc_type": "receipt",
            "title": spec.title,
            "scenario": spec.scenario,
            "expected_checks": spec.expected_checks,
        }
        if spec.stem.endswith("-photo"):
            records.append(write(spec.stem, "jpg", make_photo(data, truth), truth, meta))
        else:
            records.append(write(spec.stem, "pdf", data, truth, meta))

    data, truth = render_form()
    records.append(
        write(
            "12-catering-order-form",
            "pdf",
            data,
            truth,
            {
                "doc_type": "custom",
                "title": "Catering order form (custom fields)",
                "scenario": "A filled-in order form, read with custom fields defined for this batch.",
                "expected_checks": [],
            },
        )
    )

    records.sort(key=lambda r: r["file"])
    manifest = {
        "description": "Fictional sample paperwork for Juniper Lane Bakery. Generated by sample/generate.py.",
        "custom_fields": FORM_FIELDS,
        "documents": records,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    for r in records:
        size = (DOCS / r["file"]).stat().st_size
        print(f"{r['file']:44} {size / 1024:7.1f} KB  {r['title']}")

    import receipts  # the Receipts-mode samples, kept out of the 12-document batch

    for r in receipts.generate():
        size = (DOCS / r["file"]).stat().st_size
        print(f"{r['file']:44} {size / 1024:7.1f} KB  {r['title']}")


if __name__ == "__main__":
    main()
