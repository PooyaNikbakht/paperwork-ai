"""Document types, field specs, and the normalized extraction every provider produces."""

from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["invoice", "receipt", "custom"]
BatchMode = Literal["auto", "invoice", "receipt", "custom"]
FieldType = Literal["text", "number", "money", "date", "currency", "email"]
DocStatus = Literal["queued", "extracting", "needs_review", "ready", "approved", "failed"]
CheckStatus = Literal["pass", "warn", "fail", "skip"]
TaxKind = Literal["GST", "HST", "PST", "QST", "VAT", "Sales tax", "Other"]

Value = str | float | None


class FieldSpec(BaseModel):
    """One field to extract. Custom-field batches define their own list of these."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=60)
    type: FieldType = "text"
    required: bool = False
    description: str = Field(default="", max_length=300)


class DocSpec(BaseModel):
    """What to extract for one document type."""

    doc_type: DocType
    fields: list[FieldSpec]
    has_lines: bool = False
    label: str = ""


INVOICE = DocSpec(
    doc_type="invoice",
    label="Invoice",
    has_lines=True,
    fields=[
        FieldSpec(
            key="vendor_name",
            label="Vendor",
            required=True,
            description="The business that issued the invoice.",
        ),
        FieldSpec(
            key="vendor_address",
            label="Vendor address",
            description="The vendor's address, on one line.",
        ),
        FieldSpec(
            key="vendor_tax_number",
            label="Vendor tax number",
            description="GST/HST, QST or VAT registration number, if printed.",
        ),
        FieldSpec(
            key="bill_to",
            label="Bill to",
            description="The customer's business name the invoice is addressed to.",
        ),
        FieldSpec(key="invoice_number", label="Invoice number", required=True),
        FieldSpec(key="invoice_date", label="Invoice date", type="date", required=True),
        FieldSpec(key="due_date", label="Due date", type="date"),
        FieldSpec(
            key="currency",
            label="Currency",
            type="currency",
            required=True,
            description="ISO 4217 code such as CAD or USD.",
        ),
        FieldSpec(
            key="subtotal",
            label="Subtotal",
            type="money",
            required=True,
            description="Amount before taxes, as printed.",
        ),
        FieldSpec(
            key="total",
            label="Total",
            type="money",
            required=True,
            description="Total amount due including taxes, as printed.",
        ),
    ],
)

RECEIPT = DocSpec(
    doc_type="receipt",
    label="Receipt",
    has_lines=True,
    fields=[
        FieldSpec(key="merchant_name", label="Merchant", required=True),
        FieldSpec(key="merchant_address", label="Merchant address"),
        FieldSpec(key="date", label="Date", type="date", required=True),
        FieldSpec(
            key="currency",
            label="Currency",
            type="currency",
            required=True,
            description="ISO 4217 code such as CAD or USD.",
        ),
        FieldSpec(
            key="payment_method",
            label="Payment method",
            description="For example Visa ending 4021, Debit, or Cash.",
        ),
        FieldSpec(key="subtotal", label="Subtotal", type="money"),
        FieldSpec(key="tip", label="Tip", type="money"),
        FieldSpec(key="total", label="Total", type="money", required=True),
    ],
)

# Used for forms in auto mode when the batch defines no custom fields.
DEFAULT_CUSTOM_FIELDS: list[FieldSpec] = [
    FieldSpec(
        key="name", label="Name", required=True, description="The person who filled in the form."
    ),
    FieldSpec(key="email", label="Email", type="email"),
    FieldSpec(key="phone", label="Phone"),
    FieldSpec(key="date", label="Date", type="date", description="The main date on the form."),
    FieldSpec(
        key="summary", label="Summary", description="What the form is asking for, in one sentence."
    ),
]


def custom_spec(fields: list[FieldSpec] | None) -> DocSpec:
    return DocSpec(doc_type="custom", label="Custom fields", fields=fields or DEFAULT_CUSTOM_FIELDS)


def spec_for(doc_type: DocType, custom_fields: list[FieldSpec] | None = None) -> DocSpec:
    if doc_type == "invoice":
        return INVOICE
    if doc_type == "receipt":
        return RECEIPT
    return custom_spec(custom_fields)


# ---- Normalized extraction (stored, sent to the UI, exported) ----


class Box(BaseModel):
    """A highlight rectangle, as fractions of the page width and height (top-left origin)."""

    x0: float
    y0: float
    x1: float
    y1: float


class Source(BaseModel):
    page: int = 1
    quote: str = ""
    boxes: list[Box] = Field(default_factory=list)
    # True or False when the page has a text layer to check against; None for images.
    found: bool | None = None


class ExtractedField(BaseModel):
    key: str
    label: str
    type: FieldType
    required: bool = False
    value: Value = None
    confidence: float = 0.0
    source: Source | None = None
    edited: bool = False
    original: Value = None


class LineItem(BaseModel):
    description: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float = 0.0
    source: Source | None = None
    edited: bool = False
    # Receipts only: a suggested expense category with a short reason (see app.categories).
    category: str | None = None
    category_reason: str = ""


class TaxLine(BaseModel):
    kind: TaxKind = "Other"
    rate: float | None = None  # percent, e.g. 13 or 9.975
    amount: float | None = None
    confidence: float = 0.0
    source: Source | None = None
    edited: bool = False


class Extraction(BaseModel):
    doc_type: DocType
    has_lines: bool
    fields: list[ExtractedField]
    line_items: list[LineItem] = Field(default_factory=list)
    taxes: list[TaxLine] = Field(default_factory=list)
    # Receipts only: one suggested category for the whole receipt, and an optional job tag.
    category: str | None = None
    category_reason: str = ""
    category_edited: bool = False
    job: str | None = None

    def field(self, key: str) -> ExtractedField | None:
        return next((f for f in self.fields if f.key == key), None)

    def value(self, key: str) -> Value:
        f = self.field(key)
        return f.value if f else None

    def money(self, key: str) -> float | None:
        v = self.value(key)
        return float(v) if isinstance(v, int | float) else None


class Check(BaseModel):
    id: str
    label: str
    status: CheckStatus
    message: str
    # Field paths involved, such as "subtotal", "line_items.2.amount" or "taxes.0.amount".
    fields: list[str] = Field(default_factory=list)
