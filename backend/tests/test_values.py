from datetime import date

import pytest

from app.values import normalize_currency, normalize_date, parse_date, parse_number, vendor_key


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234.56", 1234.56),
        ("$1,014.14", 1014.14),
        ("1 234,56", 1234.56),
        ("(12.00)", -12.0),
        ("-5", -5.0),
        ("13%", 13.0),
        ("CAD 63.00", 63.0),
        (42, 42.0),
        ("", None),
        ("n/a", None),
        (None, None),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-14", date(2026, 9, 14)),
        ("Sep 14, 2026", date(2026, 9, 14)),
        ("September 18, 2026", date(2026, 9, 18)),
        ("Sept. 22, 2026", date(2026, 9, 22)),
        ("6 October 2026", date(2026, 10, 6)),
        ("10/01/2026", date(2026, 10, 1)),
        ("24/09/2026", date(2026, 9, 24)),
        ("Sat. Nov 21, 2026", date(2026, 11, 21)),
        ("31/31/2026", None),
        ("soon", None),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_normalize_date_keeps_unparseable_text():
    assert normalize_date("Oct 3, 2026") == "2026-10-03"
    assert normalize_date("next Tuesday") == "next Tuesday"
    assert normalize_date("  ") is None


def test_currency_and_vendor_keys():
    assert normalize_currency("cad") == "CAD"
    assert normalize_currency("US$") == "USD"
    assert vendor_key("Northpeak Office Supply Ltd.") == vendor_key("NORTHPEAK OFFICE SUPPLY")
