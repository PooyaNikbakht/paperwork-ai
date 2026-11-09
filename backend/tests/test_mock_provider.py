import hashlib

from fpdf import FPDF

from app.models import INVOICE, RECEIPT, custom_spec
from app.pages import parse_file
from app.providers.base import SourceFile
from app.providers.mock import MockProvider
from tests.conftest import sample_source


async def test_replays_ground_truth_for_samples():
    out = await MockProvider().extract(sample_source("10-atelier-lumiere-design.pdf"), INVOICE)
    assert out["vendor_name"]["value"] == "Atelier Lumière Design"
    assert out["invoice_date"]["value"] == "2026-10-06"
    assert out["invoice_date"]["source"]["quote"] == "6 October 2026"
    assert [t["kind"] for t in out["taxes"]] == ["GST", "QST"]
    assert all(0.93 <= out[k]["confidence"] <= 0.99 for k in ("vendor_name", "total"))


async def test_quirks_simulate_a_misread_on_the_scan():
    out = await MockProvider().extract(sample_source("06-lakeshore-cleaning-scan.png"), INVOICE)
    assert out["line_items"][2]["amount"] == 1230.0  # the page says 1,280.00
    assert out["line_items"][2]["confidence"] == 0.58
    # Images carry the generator's highlight boxes.
    assert out["total"]["source"]["boxes"]


async def test_deterministic():
    a = await MockProvider().extract(sample_source("07-harbour-street-hardware-photo.jpg"), RECEIPT)
    b = await MockProvider().extract(sample_source("07-harbour-street-hardware-photo.jpg"), RECEIPT)
    assert a == b


async def test_classify_samples():
    m = MockProvider()
    assert await m.classify(sample_source("08-greenleaf-market-receipt.pdf")) == "receipt"
    assert await m.classify(sample_source("12-catering-order-form.pdf")) == "custom"
    assert await m.classify(sample_source("04-bluewater-print-shop.pdf")) == "invoice"


def unknown_invoice() -> SourceFile:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in [
        "Oakridge Plumbing Ltd.",
        "INVOICE",
        "Invoice No: OP-3321",
        "Date: Oct 2, 2026",
        "Due date: Nov 1, 2026",
        "Subtotal: $400.00",
        "HST 13%: $52.00",
        "Total: $452.00 CAD",
    ]:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    data = bytes(pdf.output())
    parsed = parse_file(data, "application/pdf")
    return SourceFile(
        data, "application/pdf", "oakridge.pdf", hashlib.sha256(data).hexdigest(), 1, parsed.texts
    )


async def test_heuristics_for_unknown_pdfs():
    src = unknown_invoice()
    m = MockProvider()
    assert await m.classify(src) == "invoice"
    out = await m.extract(src, INVOICE)
    assert out["vendor_name"]["value"] == "Oakridge Plumbing Ltd."
    assert out["invoice_number"]["value"] == "OP-3321"
    assert out["invoice_date"]["value"] == "2026-10-02"
    assert out["due_date"]["value"] == "2026-11-01"
    assert out["subtotal"]["value"] == 400.0
    assert out["total"]["value"] == 452.0
    assert out["currency"]["value"] == "CAD"
    assert out["taxes"][0]["kind"] == "HST" and out["taxes"][0]["amount"] == 52.0
    assert out["total"]["confidence"] < 0.7


async def test_unknown_image_comes_back_empty():
    src = sample_source("07-harbour-street-hardware-photo.jpg")
    src.sha256 = "0" * 64
    out = await MockProvider().extract(src, RECEIPT)
    assert out["merchant_name"]["value"] is None
    assert out["line_items"] == []


async def test_custom_fields_from_the_sample_form():
    from app.models import FieldSpec
    from app.samples import load_manifest

    spec = custom_spec([FieldSpec(**f) for f in load_manifest()["custom_fields"]])
    out = await MockProvider().extract(sample_source("12-catering-order-form.pdf"), spec)
    assert out["customer_name"]["value"] == "Priya Raman"
    assert out["guest_count"]["value"] == 60.0
    assert out["event_date"]["value"] == "2026-11-21"
    assert out["phone"]["confidence"] == 0.66
