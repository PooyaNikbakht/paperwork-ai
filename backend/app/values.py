"""Parsing and normalizing the values people and models write: money, numbers, dates, codes."""

import re
from datetime import date, datetime

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b. %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%Y%m%d",
]

_WEEKDAY = re.compile(r"^(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+", re.I)

# Currency codes the app knows by name. Anything else is flagged by the currency check.
CURRENCIES = {
    "CAD": "Canadian dollar",
    "USD": "US dollar",
    "EUR": "Euro",
    "GBP": "British pound",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "MXN": "Mexican peso",
    "JPY": "Japanese yen",
    "CHF": "Swiss franc",
    "CNY": "Chinese yuan",
    "INR": "Indian rupee",
    "SEK": "Swedish krona",
    "NOK": "Norwegian krone",
    "DKK": "Danish krone",
}


def parse_date(text: str | None) -> date | None:
    """A date from common formats, or None. `d/m/Y` is tried after `m/d/Y`."""
    if not text:
        return None
    s = _WEEKDAY.sub("", " ".join(str(text).split())).strip()
    s = s.replace("Sept.", "Sep.").replace("Sept ", "Sep ")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def normalize_date(text: str | None) -> str | None:
    """ISO `YYYY-MM-DD` when the text parses, otherwise the text unchanged."""
    if text is None or str(text).strip() == "":
        return None
    parsed = parse_date(text)
    return parsed.isoformat() if parsed else str(text).strip()


_MONEY_JUNK = re.compile(r"[^\d.,()\-]")


def parse_number(value: object) -> float | None:
    """A number from 1,234.56, $1 234,56, (12.00), 12.5% and similar. None if unparseable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    negative = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = _MONEY_JUNK.sub("", s).strip("()-")
    if not s:
        return None
    # "1.234,56" or "1 234,56": the comma is the decimal separator.
    if (
        "," in s
        and ("." not in s or s.rfind(",") > s.rfind("."))
        and len(s.split(",")[-1]) in (1, 2)
    ):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if negative else n


def normalize_currency(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    aliases = {"$": "CAD", "C$": "CAD", "CA$": "CAD", "US$": "USD", "€": "EUR", "£": "GBP"}
    return aliases.get(s, s)


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def money_close(a: float, b: float, tolerance: float = 0.015) -> bool:
    return abs(a - b) <= tolerance


def fmt_money(x: float) -> str:
    return f"{x:,.2f}"


def norm_key(text: str | None) -> str:
    """Lowercase letters and digits only, for comparing vendor names and invoice numbers."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


_SUFFIXES = re.compile(r"\b(inc|ltd|llc|ltee|corp|co|company|limited|incorporated)\b\.?", re.I)


def vendor_key(name: str | None) -> str:
    return norm_key(_SUFFIXES.sub("", name or ""))
