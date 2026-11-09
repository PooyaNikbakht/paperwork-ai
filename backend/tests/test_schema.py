import json

from anthropic.lib._parse._transform import transform_schema

from app.extraction import normalize
from app.models import INVOICE, RECEIPT, FieldSpec, custom_spec
from app.providers.base import AIClassification, extraction_instructions, output_model


def test_invoice_schema_has_fields_lines_and_taxes():
    schema = output_model(INVOICE).model_json_schema()
    props = schema["properties"]
    for key in (
        "vendor_name",
        "invoice_number",
        "invoice_date",
        "subtotal",
        "total",
        "line_items",
        "taxes",
    ):
        assert key in props
    assert set(schema["required"]) >= {"vendor_name", "total", "line_items", "taxes"}
    defs = schema["$defs"]
    assert "quote" in defs["AISource"]["properties"]
    assert defs["AITax"]["properties"]["kind"]["enum"] == [
        "GST",
        "HST",
        "PST",
        "QST",
        "VAT",
        "Sales tax",
        "Other",
    ]
    # Money fields are numbers, text fields strings.
    assert props["total"]["$ref"].endswith("AINumber")
    assert props["vendor_name"]["$ref"].endswith("AIText")


def test_custom_schema_follows_the_user_fields_and_is_cached():
    spec = custom_spec(
        [
            FieldSpec(key="guests", label="Guests", type="number"),
            FieldSpec(key="notes", label="Notes"),
        ]
    )
    model = output_model(spec)
    assert set(model.model_json_schema()["properties"]) == {"guests", "notes"}
    assert output_model(custom_spec(list(spec.fields))) is model


def test_schemas_are_valid_for_claude_structured_outputs():
    for model in (output_model(INVOICE), output_model(RECEIPT), AIClassification):
        strict = transform_schema(model)
        text = json.dumps(strict)
        assert '"additionalProperties": false' in text
        # Constraints Claude rejects are stripped by the SDK.
        assert "minimum" not in text and "maxLength" not in text


def test_instructions_list_every_field():
    text = extraction_instructions(RECEIPT)
    for f in RECEIPT.fields:
        assert f"- {f.key}:" in text
    assert "Format YYYY-MM-DD" in text


def test_normalize_coerces_values_and_confidence():
    raw = {
        "vendor_name": {
            "value": "  Cedar &  Pine ",
            "confidence": 97,
            "source": {"page": 0, "quote": "Cedar & Pine"},
        },
        "invoice_date": {"value": "September 18, 2026", "confidence": 0.9, "source": None},
        "currency": {"value": "cad", "confidence": 0.8, "source": None},
        "total": {
            "value": "$1,014.14",
            "confidence": 0.99,
            "source": {"page": 1, "quote": "Total 1,014.14"},
        },
        "line_items": [
            {
                "description": "Boxes",
                "quantity": "4",
                "unit_price": "58.00",
                "amount": "232.00",
                "confidence": 0.9,
            }
        ],
        "taxes": [
            {"kind": "TVQ", "rate_percent": 9.975, "amount": "10.00", "confidence": 0.9},
            {"kind": "gst", "rate_percent": 5, "amount": None, "confidence": 0.9},
        ],
    }
    ex = normalize(raw, INVOICE)
    assert ex.value("vendor_name") == "Cedar & Pine"
    assert ex.field("vendor_name").confidence == 0.97
    assert ex.field("vendor_name").source.page == 1
    assert ex.value("invoice_date") == "2026-09-18"
    assert ex.value("currency") == "CAD"
    assert ex.value("total") == 1014.14
    assert ex.line_items[0].amount == 232.0
    assert [t.kind for t in ex.taxes] == ["QST"]  # tax lines without an amount are dropped
    assert ex.value("due_date") is None and ex.field("due_date").confidence == 0
