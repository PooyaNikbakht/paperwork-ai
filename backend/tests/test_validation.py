from datetime import date

from app.extraction import normalize
from app.models import INVOICE, RECEIPT, Extraction, FieldSpec, Source, custom_spec
from app.validation import CheckContext, DuplicateHit, run_checks, status_for

TODAY = date(2026, 10, 30)


def field(key, value, confidence=0.97, quote=None):
    return {
        "value": value,
        "confidence": confidence,
        "source": {"page": 1, "quote": quote or str(value)},
    }


def invoice(**overrides) -> Extraction:
    raw = {
        "vendor_name": field("vendor_name", "Northpeak Office Supply Ltd."),
        "invoice_number": field("invoice_number", "NP-24817"),
        "invoice_date": field("invoice_date", "2026-09-14"),
        "due_date": field("due_date", "2026-10-14"),
        "currency": field("currency", "CAD"),
        "subtotal": field("subtotal", 300.0),
        "total": field("total", 339.0),
        "line_items": [
            {
                "description": "Paper",
                "quantity": 2,
                "unit_price": 50,
                "amount": 100,
                "confidence": 0.95,
                "source": None,
            },
            {
                "description": "Toner",
                "quantity": 1,
                "unit_price": 200,
                "amount": 200,
                "confidence": 0.95,
                "source": None,
            },
        ],
        "taxes": [
            {"kind": "HST", "rate_percent": 13, "amount": 39.0, "confidence": 0.95, "source": None}
        ],
    }
    raw.update(overrides)
    return normalize(raw, INVOICE)


def checks(ex, **ctx):
    ctx.setdefault("today", TODAY)
    return {c.id: c for c in run_checks(ex, CheckContext(**ctx))}


def test_clean_invoice_passes_everything():
    result = checks(invoice())
    assert {k: v.status for k, v in result.items() if v.status not in ("pass", "skip")} == {}
    assert status_for(list(result.values())) == "ready"
    assert "2 line items add up to the subtotal (300.00 CAD)" in result["line_items_sum"].message


def test_missing_required_fields_fail():
    ex = invoice(
        invoice_number=field("invoice_number", None),
        total={"value": None, "confidence": 0, "source": None},
    )
    c = checks(ex)["required"]
    assert c.status == "fail"
    assert c.fields == ["invoice_number", "total"]
    assert "Invoice number and Total" in c.message


def test_line_math_names_the_line():
    lines = invoice().model_dump()["line_items"]
    ex = invoice(line_items=[lines[0], {**lines[1], "amount": 230}])
    c = checks(ex)["line_math"]
    assert c.status == "fail"
    assert c.fields == ["line_items.1.amount"]
    assert "line 2: 1 × 200.00 = 200.00, but the amount says 230.00" in c.message


def test_line_items_must_add_up_to_subtotal():
    c = checks(invoice(subtotal=field("subtotal", 340.0), total=field("total", 379.0)))[
        "line_items_sum"
    ]
    assert c.status == "fail"
    assert "add up to 300.00, but the subtotal is 340.00, a difference of 40.00" in c.message


def test_line_items_compare_to_total_when_no_subtotal():
    ex = normalize(
        {
            "merchant_name": field("m", "Shop"),
            "date": field("d", "2026-10-03"),
            "currency": field("c", "CAD"),
            "total": field("t", 11.3),
            "line_items": [
                {
                    "description": "A",
                    "quantity": 1,
                    "unit_price": 10,
                    "amount": 10,
                    "confidence": 0.9,
                }
            ],
            "taxes": [{"kind": "HST", "rate_percent": 13, "amount": 1.3, "confidence": 0.9}],
        },
        RECEIPT,
    )
    assert checks(ex)["line_items_sum"].status == "pass"


def test_totals_must_add_up():
    c = checks(invoice(total=field("total", 349.0)))["totals"]
    assert c.status == "fail"
    assert "come to 339.00, but the total says 349.00, a difference of 10.00" in c.message
    assert "total" in c.fields


def test_tax_rate_unknown_for_kind_warns():
    ex = invoice(
        taxes=[{"kind": "HST", "rate_percent": 12, "amount": 36.0, "confidence": 0.9}],
        total=field("total", 336.0),
    )
    c = checks(ex)["tax_rates"]
    assert c.status == "warn"
    assert "HST is 13% in Ontario" in c.message


def test_tax_overcharge_fails():
    ex = invoice(
        taxes=[{"kind": "GST", "rate_percent": 5, "amount": 25.0, "confidence": 0.9}],
        total=field("total", 325.0),
    )
    c = checks(ex)["tax_rates"]
    assert c.status == "fail"
    assert "GST at 5% of 300.00 is 15.00, but the document charges 25.00" in c.message


def test_partial_tax_is_fine_on_receipts_but_flagged_on_invoices():
    taxes = [{"kind": "HST", "rate_percent": 13, "amount": 13.0, "confidence": 0.9}]
    assert checks(invoice(taxes=taxes, total=field("total", 313.0)))["tax_rates"].status == "warn"
    receipt = normalize(
        {
            "merchant_name": field("m", "Greenleaf"),
            "date": field("d", "2026-10-12"),
            "currency": field("c", "CAD"),
            "subtotal": field("s", 300.0),
            "total": field("t", 313.0),
            "taxes": taxes,
        },
        RECEIPT,
    )
    c = checks(receipt)["tax_rates"]
    assert c.status == "pass"
    assert "tax-exempt" in c.message


def test_quebec_and_bc_rates_pass():
    ex = invoice(
        taxes=[
            {"kind": "GST", "rate_percent": 5, "amount": 15.0, "confidence": 0.9},
            {"kind": "QST", "rate_percent": 9.975, "amount": 29.93, "confidence": 0.9},
        ],
        total=field("total", 344.93),
    )
    assert checks(ex)["tax_rates"].status == "pass"
    assert checks(ex)["totals"].status == "pass"


def test_dates_must_parse_and_be_in_order():
    c = checks(invoice(due_date=field("due_date", "2026-09-01")))["dates"]
    assert c.status == "fail"
    assert "due date is before the invoice date" in c.message
    c = checks(invoice(invoice_date=field("invoice_date", "31/31/2026")))["dates"]
    assert c.status == "fail"
    assert "isn't a date" in c.message
    c = checks(
        invoice(
            invoice_date=field("invoice_date", "2028-01-01"),
            due_date=field("due_date", "2028-02-01"),
        )
    )["dates"]
    assert c.status == "warn"


def test_currency_must_be_known_and_consistent():
    assert checks(invoice(currency=field("currency", "CDN")))["currency"].status == "fail"
    c = checks(invoice(), page_texts=["Total due (USD) 339.00"], has_text_layer=True)["currency"]
    assert c.status == "fail"
    assert "also mentions USD" in c.message
    # Quotes count too, which matters for scans without a text layer.
    ex = invoice(total=field("total", 339.0, quote="Total due (USD) 339.00"))
    assert checks(ex)["currency"].status == "fail"


def test_duplicate_flagged_with_the_other_file():
    hit = DuplicateHit("doc_1", "first.pdf", same_batch=True, approved=False)
    c = checks(invoice(), duplicates=[hit])["duplicate"]
    assert c.status == "fail"
    assert "first.pdf" in c.message and "earlier in this batch" in c.message
    assert checks(invoice())["duplicate"].status == "pass"


def test_sources_not_found_warn_only_with_text_layer():
    ex = invoice()
    total = ex.field("total")
    total.source = Source(page=1, quote="Total 999", found=False)
    assert checks(ex, has_text_layer=True)["sources"].status == "warn"
    assert checks(ex, has_text_layer=False)["sources"].status == "skip"
    total.edited = True
    assert checks(ex, has_text_layer=True)["sources"].status == "pass"


def test_low_confidence_warns_until_edited():
    ex = invoice(vendor_name=field("vendor_name", "Northpeak", confidence=0.4))
    c = checks(ex)["confidence"]
    assert c.status == "warn"
    assert "Vendor (40%)" in c.message
    ex.field("vendor_name").edited = True
    assert checks(ex)["confidence"].status == "pass"


def test_custom_fields_check_formats_and_required():
    spec = custom_spec(
        [
            FieldSpec(key="name", label="Name", required=True),
            FieldSpec(key="email", label="Email", type="email"),
            FieldSpec(key="when", label="When", type="date"),
        ]
    )
    ex = normalize(
        {
            "name": field("n", None),
            "email": field("e", "not-an-email"),
            "when": field("w", "Nov 21, 2026"),
        },
        spec,
    )
    result = checks(ex)
    assert result["required"].status == "fail"
    assert result["formats"].status == "fail"
    assert result["dates"].status == "pass"
    assert ex.value("when") == "2026-11-21"
    assert "line_math" not in result
