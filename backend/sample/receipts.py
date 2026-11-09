"""Three sample job receipts for the Receipts mode: phone photos of crumpled till slips.

Every business here is fictional. Called from generate.py (run `make sample`). Amounts are computed
with Decimal while the receipt is drawn, so they always add up, except on purpose in the
equipment rental slip, where the printed HST is 10.00 short of 13% so the math check has
something to catch.

Writes next to this file: documents/*.jpg, truth/*.json and receipts_manifest.json.
"""

import hashlib
import io
import json
import random
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import generate as g
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent


@dataclass
class Slip:
    stem: str
    title: str
    scenario: str
    merchant: str
    address: list[str]
    tax_line: str
    header_extra: list[str]
    when: str  # as printed
    iso_date: str
    lines: list[g.Line]
    payment: str
    payment_quote: str
    footer: list[str]
    expected_categories: list[str]
    expected_receipt_category: str
    tax_rate: Decimal = Decimal(13)
    printed_tax_delta: Decimal = Decimal(0)  # a deliberate misprint on the tax line
    qty_format: str = "{qty} @ {unit}"
    unit_decimals: int = 2
    # Photo settings
    angle: float = -2.5
    bg: tuple[int, int, int] = (92, 74, 58)
    seed: int = 1
    expected_checks: list[str] = field(default_factory=list)


def render_slip(spec: Slip) -> tuple[bytes, dict[str, Any]]:
    rec = g.Recorder("receipt")
    subtotal = sum((ln.amount for ln in spec.lines), Decimal(0))
    true_tax = g.q2(subtotal * spec.tax_rate / 100)
    printed_tax = true_tax + spec.printed_tax_delta
    total = subtotal + true_tax  # the till total is right; the printed tax line is the slip's slip
    height = 74 + len(spec.lines) * 8.0 + len(spec.header_extra) * 4.2 + len(spec.footer) * 4
    pdf = g.new_pdf(unit="mm", format=(80, height))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    w = 70
    pdf.set_text_color(25, 25, 25)

    def row(text: str, size: float = 8.5, bold: bool = False, h: float = 4.2) -> None:
        pdf.set_x(5)
        pdf.set_font("Courier", "B" if bold else "", size)
        pdf.cell(w, h, text, align="C", new_x="LMARGIN", new_y="NEXT")

    def two(left: str, right: str, bold: bool = False) -> str:
        pdf.set_x(5)
        pdf.set_font("Courier", "B" if bold else "", 8.5)
        pdf.cell(w - 22, 4.4, left)
        pdf.cell(22, 4.4, right, align="R", new_x="LMARGIN", new_y="NEXT")
        return f"{left} {right}"

    pdf.set_y(8)
    row(spec.merchant.upper(), 10.5, True, h=6)
    rec.field("merchant_name", spec.merchant, spec.merchant.upper())
    for a in spec.address:
        row(a)
    rec.field("merchant_address", ", ".join(spec.address), spec.address[0])
    row(spec.tax_line)
    for extra in spec.header_extra:
        row(extra)
    pdf.ln(2)
    row(spec.when)
    rec.field("date", spec.iso_date, spec.when)
    row("-" * 32)
    for ln in spec.lines:
        two(ln.description, g.money(ln.amount))
        rec.line(ln, ln.description, 1)
        if ln.qty != 1:
            pdf.set_x(9)
            pdf.set_font("Courier", "", 7.5)
            sub = spec.qty_format.format(
                qty=f"{ln.qty.normalize():f}", unit=f"{ln.unit:.{spec.unit_decimals}f}"
            )
            pdf.cell(w - 4, 3.8, sub, new_x="LMARGIN", new_y="NEXT")
    row("-" * 32)
    rec.field("subtotal", g.num(subtotal), two("SUBTOTAL", g.money(subtotal)))
    rate = f"{spec.tax_rate.normalize():f}"
    rec.tax("HST", spec.tax_rate, printed_tax, two(f"HST {rate}%", g.money(printed_tax)), 1)
    rec.missing("tip")
    rec.field("total", g.num(total), two("TOTAL", g.money(total), bold=True))
    rec.field("currency", "CAD", "ALL PRICES IN CAD")
    pdf.ln(2)
    row(spec.payment_quote)
    rec.field("payment_method", spec.payment, spec.payment_quote)
    auth = int(hashlib.sha256(spec.stem.encode()).hexdigest()[:6], 16) % 90000 + 10000
    row(f"APPROVED  AUTH 0{auth}")
    pdf.ln(2)
    row("ALL PRICES IN CAD", 7.5)
    for text in spec.footer:
        row(text, 7.5)
    truth = rec.as_dict()
    truth["page_count"] = 1
    truth["expected_categories"] = {
        "lines": spec.expected_categories,
        "receipt": spec.expected_receipt_category,
    }
    return bytes(pdf.output()), truth


# ---- The phone-photo look ----


def _blotches(size: tuple[int, int], seed: int, strength: float, cell: int = 36) -> Image.Image:
    """Soft low-frequency light and dark patches, as a multiply map (255 means unchanged)."""
    rnd = random.Random(seed)
    small = (max(2, size[0] // cell), max(2, size[1] // cell))
    noise = Image.frombytes("L", small, rnd.randbytes(small[0] * small[1]))
    noise = noise.resize(size, Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(cell))
    return noise.point(lambda v: int(255 - strength * (255 - v) / 255 * 120))


def _creases(size: tuple[int, int], seed: int, count: int) -> Image.Image:
    """Thin dark crumple lines across the paper, as a multiply map."""
    rnd = random.Random(seed)
    shade = Image.new("L", size, 255)
    draw = ImageDraw.Draw(shade)
    w, h = size
    for _ in range(count):
        y = rnd.uniform(0.05, 0.95) * h
        x = rnd.uniform(-0.1, 0.5) * w
        pts = [(x, y)]
        while x < w * 1.05:
            x += rnd.uniform(0.08, 0.2) * w
            y += rnd.uniform(-0.05, 0.05) * h
            pts.append((x, y))
        draw.line(pts, fill=rnd.randrange(150, 205), width=rnd.choice([2, 2, 3]), joint="curve")
    return shade.filter(ImageFilter.GaussianBlur(1.6))


def phone_photo(pdf_bytes: bytes, truth: dict[str, Any], spec: Slip) -> bytes:
    entries = g.boxes_for(pdf_bytes, truth)
    paper = g.render_page(pdf_bytes, 230)
    paper = Image.blend(paper, Image.new("RGB", paper.size, (244, 241, 232)), 0.2)
    # Crumple: creases and soft patches darken the paper without moving any text.
    shade = ImageChops.multiply(
        _creases(paper.size, spec.seed, 5), _blotches(paper.size, spec.seed + 1, 0.55, 90)
    )
    paper = ImageChops.multiply(paper, Image.merge("RGB", (shade, shade, shade)))
    rotated = paper.rotate(
        spec.angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0)
    )
    mask = Image.new("L", paper.size, 255).rotate(spec.angle, expand=True, fillcolor=0)
    bg_w, bg_h = rotated.width + 300, rotated.height + 260
    bg = Image.new("RGB", (bg_w, bg_h), spec.bg)
    bg = g.add_noise(bg, 46, seed=spec.seed + 2)
    bg = ImageChops.multiply(
        bg, Image.merge("RGB", (_blotches(bg.size, spec.seed + 3, 0.5, 120),) * 3)
    )
    offset = (150, 110)
    # A soft shadow under the paper, offset down and to the right.
    shadow = Image.new("L", bg.size, 0)
    shadow.paste(mask.point(lambda v: 110 if v else 0), (offset[0] + 16, offset[1] + 22))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    bg = Image.composite(Image.new("RGB", bg.size, (20, 17, 14)), bg, shadow)
    bg.paste(rotated, offset, mask)
    # Uneven light from one side, then a little camera softness.
    light = Image.linear_gradient("L").rotate(90 if spec.seed % 2 else -90).resize(bg.size)
    bg = Image.composite(bg, Image.blend(bg, Image.new("RGB", bg.size, (30, 26, 22)), 0.3), light)
    bg = bg.filter(ImageFilter.GaussianBlur(0.8))
    g.transform_boxes(entries, paper.size, spec.angle, rotated.size, offset, bg.size)
    bg.thumbnail((1400, 2400))
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=80)
    return buf.getvalue()


# ---- The three slips ----

D = g.D

SLIPS = [
    Slip(
        stem="13-eastgate-lumber-hardware-photo",
        title="Lumber yard receipt (materials, one tool, gloves)",
        scenario="A creased phone photo of a lumber and hardware till slip. All amounts add up.",
        merchant="Eastgate Lumber and Hardware",
        address=["118 Weber St N", "Waterloo, ON N2J 3H1"],
        tax_line="HST# 83921 4407 RT0001",
        header_extra=[],
        when="2026-10-21  07:42",
        iso_date="2026-10-21",
        lines=[
            g.Line("2X4X8 SPF STUD", D(24), D("4.29")),
            g.Line("PLYWOOD 1/2 4X8", D(6), D("38.97")),
            g.Line("DECK SCREWS 3IN 5LB", D(2), D("29.99")),
            g.Line("LOCTITE PL CAULK", D(4), D("8.49")),
            g.Line("UTILITY KNIFE 18MM", D(1), D("12.99")),
            g.Line("WORK GLOVES LG", D(1), D("14.99")),
        ],
        payment="Visa ending 4021",
        payment_quote="VISA ****4021",
        footer=["CONTRACTOR COUNTER", "RETURNS WITHIN 30 DAYS"],
        expected_categories=[
            "Materials and supplies",
            "Materials and supplies",
            "Materials and supplies",
            "Materials and supplies",
            "Tools",
            "Safety gear and workwear",
        ],
        expected_receipt_category="Materials and supplies",
        angle=-2.6,
        seed=11,
    ),
    Slip(
        stem="14-trailhead-fuel-and-go-photo",
        title="Fuel stop receipt (fuel and a coffee and sandwich)",
        scenario="A phone photo of a fuel station slip: fuel by the litre, plus two food items.",
        merchant="Trailhead Fuel and Go",
        address=["4 Dunlop St W", "Barrie, ON L4N 1A1"],
        tax_line="HST# 71844 2093 RT0001",
        header_extra=["PUMP 4"],
        when="2026-10-22  06:18",
        iso_date="2026-10-22",
        lines=[
            g.Line("REGULAR UNLEADED", D("62.410"), D("1.589")),
            g.Line("COFFEE LARGE", D(1), D("2.49")),
            g.Line("BREAKFAST SANDWICH", D(1), D("5.99")),
        ],
        payment="Mastercard ending 7715",
        payment_quote="MASTERCARD ****7715",
        footer=["THANKS FOR STOPPING IN"],
        expected_categories=["Vehicle fuel", "Meals", "Meals"],
        expected_receipt_category="Vehicle fuel",
        qty_format="{qty} L @ {unit}/L",
        unit_decimals=3,
        angle=3.4,
        bg=(70, 72, 76),
        seed=22,
    ),
    Slip(
        stem="15-kestrel-equipment-rentals-photo",
        title="Equipment rental slip (printed HST is wrong)",
        scenario=(
            "A phone photo of a one-day excavator rental. The HST line is printed 10.00 too low, "
            "so the printed amounts don't add up to the total."
        ),
        merchant="Kestrel Equipment Rentals",
        address=["77 Burlington St E", "Hamilton, ON L8L 4H2"],
        tax_line="HST# 90356 1182 RT0001",
        header_extra=["RENTAL CONTRACT K-20417"],
        when="2026-10-23  08:05",
        iso_date="2026-10-23",
        lines=[
            g.Line("MINI EXCAVATOR 1 DAY", D(1), D("285.00")),
            g.Line("HYDRAULIC BREAKER ATT", D(1), D("65.00")),
            g.Line("DELIVERY AND PICKUP", D(1), D("60.00")),
            g.Line("DAMAGE WAIVER", D(1), D("22.80")),
        ],
        payment="Amex ending 1007",
        payment_quote="AMEX ****1007",
        footer=["RETURN BY 8:00 AM NEXT DAY"],
        expected_categories=["Equipment rental"] * 4,
        expected_receipt_category="Equipment rental",
        printed_tax_delta=D("-10.00"),
        angle=-1.4,
        bg=(118, 112, 100),
        seed=33,
        expected_checks=["totals"],
    ),
]


def generate() -> list[dict[str, Any]]:
    records = []
    for spec in SLIPS:
        pdf, truth = render_slip(spec)
        meta = {
            "doc_type": "receipt",
            "title": spec.title,
            "scenario": spec.scenario,
            "expected_checks": spec.expected_checks,
        }
        records.append(g.write(spec.stem, "jpg", phone_photo(pdf, truth, spec), truth, meta))
    manifest = {
        "description": "Fictional sample job receipts. Generated by sample/receipts.py.",
        "documents": sorted(records, key=lambda r: r["file"]),
    }
    (HERE / "receipts_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return records
