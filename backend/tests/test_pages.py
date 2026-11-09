import io

import pytest
from PIL import Image

from app.extraction import locate_sources, normalize
from app.models import INVOICE
from app.pages import QuoteLocator, UnreadableFile, count_pages, parse_file, sniff
from tests.conftest import sample_bytes, truth


def test_sniff_by_signature_not_name():
    assert sniff(b"%PDF-1.7\n...") == "application/pdf"
    assert sniff(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert sniff(b"\xff\xd8\xff\xe0....") == "image/jpeg"
    assert sniff(b"<html>") is None


def test_parse_pdf_renders_pages_and_text():
    parsed = parse_file(sample_bytes("03-maple-ridge-flour-mill.pdf"), "application/pdf", width=700)
    assert parsed.page_count == 2
    assert parsed.pages[0].width == 700
    assert parsed.has_text_layer
    assert "Fuel surcharge" in parsed.texts[1]


def test_parse_image_has_no_text_layer():
    parsed = parse_file(sample_bytes("07-harbour-street-hardware-photo.jpg"), "image/jpeg")
    assert parsed.page_count == 1
    assert not parsed.has_text_layer


def test_unreadable_pdf():
    with pytest.raises(UnreadableFile):
        count_pages(b"%PDF-1.4 this is not really a pdf", "application/pdf")


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (200, 100), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    parsed = parse_file(buf.getvalue(), "image/jpeg")
    assert (parsed.pages[0].width, parsed.pages[0].height) == (100, 200)


@pytest.mark.parametrize(
    "stem",
    [
        "01-northpeak-office-supply",
        "02-cedar-pine-packaging",
        "03-maple-ridge-flour-mill",
        "08-greenleaf-market-receipt",
        "10-atelier-lumiere-design",
        "12-catering-order-form",
    ],
)
def test_every_ground_truth_quote_is_found_on_its_page(stem):
    t = truth(stem)
    data = sample_bytes(t["file"])
    with QuoteLocator(data) as loc:
        items = [*t["fields"].values(), *t["line_items"], *t["taxes"]]
        for item in items:
            if item.get("quote"):
                boxes = loc.find(item["page"], item["quote"])
                assert boxes, f"{item['quote']!r} not found"
                b = boxes[0]
                assert 0 <= b.x0 < b.x1 <= 1 and 0 <= b.y0 < b.y1 <= 1


def test_locate_sources_marks_found_and_missing():
    raw = {
        "vendor_name": {
            "value": "Northpeak",
            "confidence": 0.9,
            "source": {"page": 1, "quote": "Northpeak Office Supply Ltd."},
        },
        "total": {
            "value": 1014.14,
            "confidence": 0.9,
            "source": {"page": 2, "quote": "Total (CAD) 1,014.14"},
        },
        "subtotal": {
            "value": 897.47,
            "confidence": 0.9,
            "source": {"page": 1, "quote": "Subtotal 9,999.99"},
        },
    }
    ex = normalize(raw, INVOICE)
    locate_sources(ex, sample_bytes("01-northpeak-office-supply.pdf"), True)
    assert ex.field("vendor_name").source.found is True
    assert ex.field("vendor_name").source.boxes
    # The wrong page is corrected when the quote is on another page.
    assert ex.field("total").source.found is True and ex.field("total").source.page == 1
    assert ex.field("subtotal").source.found is False
