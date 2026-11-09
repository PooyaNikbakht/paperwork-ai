"""Suggested expense categories for receipts.

These are suggestions for a bookkeeper or accountant to review. They are not tax advice and say
nothing about what can be claimed. The AI providers suggest a category with a short reason per
line; this module defines the allowed list and a small rule-based categorizer that is used in demo
mode and as a fallback whenever a provider's suggestion is missing or not on the list.
"""

import re
from dataclasses import dataclass
from typing import Literal, get_args

Category = Literal[
    "Materials and supplies",
    "Vehicle fuel",
    "Equipment rental",
    "Tools",
    "Safety gear and workwear",
    "Meals",
    "Office and admin",
    "Other",
]
CATEGORIES: tuple[str, ...] = get_args(Category)
OTHER = "Other"

DISCLAIMER = "Suggested categories, for your bookkeeper or accountant to review. Not tax advice."


@dataclass(frozen=True)
class Suggestion:
    category: str
    reason: str


# Checked in this order for each line, so "tape measure" lands in Tools before "tape".
_LINE_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "Equipment rental",
        re.compile(
            r"\b(rental|rent|damage waiver|per day|daily rate|weekly rate|excavator|scaffold)", re.I
        ),
    ),
    (
        "Vehicle fuel",
        re.compile(r"\b(unleaded|diesel|gasoline|fuel|petrol|midgrade|propane exchange)\b", re.I),
    ),
    (
        "Safety gear and workwear",
        re.compile(
            r"\b(gloves?|hard hat|safety glasses|goggles|hi-?vis|vest|respirator|dust mask|"
            r"ear ?plugs?|earmuffs?|coveralls?|work boots?)\b",
            re.I,
        ),
    ),
    (
        "Tools",
        re.compile(
            r"\b(drill|saw|hammer|wrench|pliers?|screwdriver|utility knife|tape measure|"
            r"level|ratchet|socket set|chisel|sander|grinder|toolbox|pry bar|stud finder)\b",
            re.I,
        ),
    ),
    (
        "Materials and supplies",
        re.compile(
            r"\b(lumber|2x4|2x6|2x8|4x8|plywood|osb|drywall|screws?|nails?|bolts?|anchors?|"
            r"caulk(ing)?|sealant|paint|primer|concrete|cement|mortar|gravel|insulation|pipe|"
            r"fitting|wire|cable|conduit|shingles?|adhesive|glue|tape|studs?|fasteners?|"
            r"sandpaper|trim|stain|shims?|grout|tile)\b",
            re.I,
        ),
    ),
    (
        "Meals",
        re.compile(
            r"\b(coffee|latte|tea|sandwich|breakfast|lunch|dinner|burger|pizza|combo|meal|"
            r"donuts?|muffin|soda|pop|sub|wrap|fries)\b",
            re.I,
        ),
    ),
    (
        "Office and admin",
        re.compile(
            r"\b(printer|toner|copy paper|pens?|notebook|stapler|postage|stamps?|envelopes?)\b",
            re.I,
        ),
    ),
]

# When no line keyword matches, the kind of business is a reasonable default.
_VENDOR_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Equipment rental", re.compile(r"\b(rentals?|equipment|hire)\b", re.I)),
    (
        "Vehicle fuel",
        re.compile(r"\b(fuel|gas|petro|petroleum|esso|shell|husky|pioneer|sunoco)\b", re.I),
    ),
    (
        "Materials and supplies",
        re.compile(
            r"\b(hardware|lumber|timber|building supply|supply|home centre|electric|plumbing)\b",
            re.I,
        ),
    ),
    (
        "Meals",
        re.compile(
            r"\b(cafe|coffee|diner|grill|restaurant|pizza|kitchen|bakery|tim hortons)\b", re.I
        ),
    ),
    ("Office and admin", re.compile(r"\b(office|stationery|staples)\b", re.I)),
]

NO_MATCH = Suggestion(OTHER, "No clear match. Please choose a category.")


def clean_category(value: object) -> str | None:
    """The canonical category for a provider's or user's answer, or None if it isn't on the list."""
    if not isinstance(value, str):
        return None
    wanted = " ".join(value.split()).casefold()
    return next((c for c in CATEGORIES if c.casefold() == wanted), None)


def suggest_for_line(description: str, vendor: str | None = None) -> Suggestion:
    for category, pattern in _LINE_RULES:
        if m := pattern.search(description or ""):
            return Suggestion(category, f'The description mentions "{m.group(0).lower()}".')
    return suggest_for_vendor(vendor)


def suggest_for_vendor(vendor: str | None) -> Suggestion:
    for category, pattern in _VENDOR_RULES:
        if pattern.search(vendor or ""):
            return Suggestion(category, f"Based on the type of business ({vendor}).")
    return NO_MATCH


def summarize_receipt(lines: list[tuple[str, float]], vendor: str | None) -> Suggestion:
    """One category for the whole receipt from its lines: the one with the largest amount."""
    if not lines:
        return suggest_for_vendor(vendor)
    totals: dict[str, float] = {}
    for category, amount in lines:
        totals[category] = totals.get(category, 0.0) + abs(amount)
    if not any(totals.values()):
        totals = {c: float(sum(1 for k, _ in lines if k == c)) for c in totals}
    top = max(totals, key=lambda c: totals[c])
    share = totals[top] / (sum(totals.values()) or 1)
    if len(totals) == 1:
        return Suggestion(top, f"All {len(lines)} line items look like {top.lower()}.")
    others = ", ".join(sorted(c for c in totals if c != top))
    return Suggestion(top, f"Largest share of the receipt ({share:.0%}). Other lines: {others}.")


def add_suggestions(raw: dict) -> dict:
    """Fill a receipt's raw provider output with category suggestions, the way a model would.

    Used by demo mode so it returns the same shape the live providers are asked for.
    """
    vendor = (raw.get("merchant_name") or {}).get("value")
    vendor = vendor if isinstance(vendor, str) else None
    pairs = []
    for line in raw.get("line_items") or []:
        found = suggest_for_line(line.get("description", ""), vendor)
        line["category"], line["category_reason"] = found.category, found.reason
        pairs.append((found.category, line.get("amount") or 0.0))
    top = summarize_receipt(pairs, vendor)
    raw["expense_category"] = {"category": top.category, "reason": top.reason}
    return raw
