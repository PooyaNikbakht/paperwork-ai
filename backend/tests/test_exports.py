import csv
import io
import time

from openpyxl import load_workbook

from app.exports import export_csv, export_sheets, export_xlsx, safe_text
from app.extraction import normalize
from app.models import INVOICE
from app.store import Document
from app.validation import CheckContext, run_checks


def doc(vendor="Northpeak", total=113.0, filename="a.pdf") -> Document:
    ex = normalize(
        {
            "vendor_name": {"value": vendor, "confidence": 0.9},
            "invoice_number": {"value": "A-1", "confidence": 0.9},
            "invoice_date": {"value": "2026-09-14", "confidence": 0.9},
            "currency": {"value": "CAD", "confidence": 0.9},
            "subtotal": {"value": 100, "confidence": 0.9},
            "total": {"value": total, "confidence": 0.9},
            "line_items": [
                {
                    "description": '=HYPERLINK("http://x")',
                    "quantity": 1,
                    "unit_price": 100,
                    "amount": 100,
                    "confidence": 0.9,
                }
            ],
            "taxes": [{"kind": "HST", "rate_percent": 13, "amount": 13, "confidence": 0.9}],
        },
        INVOICE,
    )
    now = time.time()
    return Document(
        id="doc_1",
        batch_id="bat_1",
        position=0,
        filename=filename,
        media_type="application/pdf",
        size=1,
        sha256="x",
        status="approved",
        created_at=now,
        updated_at=now,
        doc_type="invoice",
        extraction=ex,
        checks=run_checks(ex, CheckContext()),
        provider="mock",
    )


def test_formula_injection_is_neutralized():
    assert safe_text("=SUM(A1)") == "'=SUM(A1)"
    assert safe_text("@cmd") == "'@cmd"
    assert safe_text("Northpeak") == "Northpeak"
    assert safe_text(-5.0) == -5.0


def test_csv_one_row_per_document_with_tax_columns():
    rows = list(csv.DictReader(io.StringIO(export_csv([doc("=evil()")]).decode("utf-8-sig"))))
    assert rows[0]["party"] == "'=evil()"
    assert rows[0]["hst"] == "13.00"
    assert rows[0]["total"] == "113.00"
    assert rows[0]["provider"] == "demo"
    assert rows[0]["checks_flagged"] == "0"


def test_sheets_csv_is_one_row_per_line_without_bom():
    data = export_sheets([doc()])
    assert not data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert rows[0]["description"].startswith("'=HYPERLINK")
    assert rows[0]["date"] == "2026-09-14"
    assert rows[0]["total"] == "113.00"


def test_xlsx_types_and_formats():
    wb = load_workbook(io.BytesIO(export_xlsx([doc(), doc(filename="b.pdf")])))
    ws = wb["Documents"]
    header = [c.value for c in ws[1]]
    total_col = header.index("Total") + 1
    date_col = header.index("Date") + 1
    assert ws.cell(2, total_col).value == 113.0
    assert ws.cell(2, total_col).number_format == "#,##0.00"
    assert ws.cell(2, date_col).value.year == 2026
    assert ws.freeze_panes == "A2"
    assert wb["Line items"].cell(2, 7).value.startswith("'=")
    assert wb["Checks"].max_row > 2
