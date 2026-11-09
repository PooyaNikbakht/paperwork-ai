import pytest

from app.categories import (
    CATEGORIES,
    DISCLAIMER,
    OTHER,
    add_suggestions,
    clean_category,
    suggest_for_line,
    suggest_for_vendor,
    summarize_receipt,
)
from app.extraction import normalize
from app.models import INVOICE, RECEIPT
from app.providers.base import extraction_instructions, output_model


def test_category_list_is_closed_and_includes_the_basics():
    for name in ("Materials and supplies", "Vehicle fuel", "Equipment rental", "Tools", "Meals"):
        assert name in CATEGORIES
    assert CATEGORIES[-1] == OTHER
    assert len(set(CATEGORIES)) == len(CATEGORIES)


def test_clean_category_accepts_only_listed_values():
    assert clean_category("  vehicle FUEL ") == "Vehicle fuel"
    assert clean_category("Tax write-off") is None
    assert clean_category(None) is None
    assert clean_category(5) is None


def test_receipt_schema_constrains_categories_and_invoice_schema_has_none():
    schema = output_model(RECEIPT).model_json_schema()
    assert "expense_category" in schema["properties"]
    defs = schema["$defs"]
    assert set(defs["AIExpenseCategory"]["properties"]["category"]["enum"]) == set(CATEGORIES)
    assert "category" in defs["AIReceiptLineItem"]["required"]
    assert "AIReceiptLineItem" not in output_model(INVOICE).model_json_schema()["$defs"]


def test_instructions_say_suggested_for_review_and_never_tax_advice():
    text = extraction_instructions(RECEIPT).lower()
    assert "bookkeeper or accountant to review" in text
    assert "never say anything is a tax write-off" in text
    assert "write-off" not in DISCLAIMER.lower()
    assert "not tax advice" in DISCLAIMER.lower()


@pytest.mark.parametrize(
    ("description", "vendor", "expected"),
    [
        ("2X4X8 SPF STUD", "Eastgate Lumber and Hardware", "Materials and supplies"),
        ("DECK SCREWS 3IN 5LB", None, "Materials and supplies"),
        ("UTILITY KNIFE 18MM", "Eastgate Lumber and Hardware", "Tools"),
        ("TAPE MEASURE 25FT", None, "Tools"),
        ("MASKING TAPE", None, "Materials and supplies"),
        ("WORK GLOVES LG", None, "Safety gear and workwear"),
        ("REGULAR UNLEADED", "Trailhead Fuel and Go", "Vehicle fuel"),
        ("COFFEE LARGE", "Trailhead Fuel and Go", "Meals"),
        ("MINI EXCAVATOR 1 DAY", None, "Equipment rental"),
        ("DELIVERY AND PICKUP", "Kestrel Equipment Rentals", "Equipment rental"),
        ("GIFT CARD", "Some Shop", "Other"),
    ],
)
def test_suggest_for_line(description, vendor, expected):
    found = suggest_for_line(description, vendor)
    assert found.category == expected
    assert found.reason


def test_vendor_fallback_and_no_match_asks_the_user():
    assert suggest_for_vendor("Maple Cafe").category == "Meals"
    assert suggest_for_vendor("Acme").category == OTHER
    assert "choose" in suggest_for_vendor("Acme").reason


def test_receipt_category_is_the_largest_share():
    top = summarize_receipt([("Vehicle fuel", 99.17), ("Meals", 8.48)], "Trailhead Fuel and Go")
    assert top.category == "Vehicle fuel"
    assert "Meals" in top.reason and "92%" in top.reason
    one = summarize_receipt([("Tools", 10.0), ("Tools", 5.0)], None)
    assert one.category == "Tools" and "All 2" in one.reason
    assert summarize_receipt([], "Kestrel Equipment Rentals").category == "Equipment rental"


def raw_receipt(**extra):
    raw = {
        "merchant_name": {"value": "Eastgate Lumber and Hardware", "confidence": 0.9},
        "date": {"value": "2026-10-21", "confidence": 0.9},
        "currency": {"value": "CAD", "confidence": 0.9},
        "total": {"value": 22.6, "confidence": 0.9},
        "line_items": [
            {"description": "UTILITY KNIFE", "quantity": 1, "unit_price": 20, "amount": 20},
            {"description": "GIFT CARD", "quantity": 1, "unit_price": 0, "amount": 0},
        ],
        "taxes": [],
    }
    raw.update(extra)
    return raw


def test_normalize_keeps_valid_provider_categories_and_repairs_bad_ones():
    raw = raw_receipt()
    raw["line_items"][0].update(category="Meals", category_reason="Looks like lunch.")
    raw["line_items"][1].update(category="Deductible stuff", category_reason="x")
    raw["expense_category"] = {"category": "Not a category", "reason": "x"}
    ex = normalize(raw, RECEIPT)
    assert ex.line_items[0].category == "Meals"
    assert ex.line_items[0].category_reason == "Looks like lunch."
    # An answer that isn't on the list is replaced by the rule-based suggestion (here: the
    # lumber yard's usual category, since GIFT CARD matches nothing).
    assert ex.line_items[1].category == "Materials and supplies"
    assert ex.category == "Meals"  # largest share, from the lines


def test_normalize_uses_the_providers_receipt_category_when_valid():
    ex = normalize(
        raw_receipt(expense_category={"category": "tools", "reason": "A knife."}), RECEIPT
    )
    assert (ex.category, ex.category_reason) == ("Tools", "A knife.")
    assert ex.category_edited is False and ex.job is None


def test_invoices_get_no_categories():
    assert normalize({}, INVOICE).category is None


def test_add_suggestions_matches_the_live_shape():
    raw = add_suggestions(raw_receipt())
    assert raw["expense_category"]["category"] == "Tools"
    assert all(li["category"] in CATEGORIES for li in raw["line_items"])
