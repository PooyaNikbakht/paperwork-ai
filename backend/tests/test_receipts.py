import csv
import io

from openpyxl import load_workbook

from app.exports import category_summary, summary_with_total
from app.extraction import normalize
from app.models import RECEIPT
from app.providers.anthropic import AnthropicProvider
from app.providers.mock import MockProvider
from app.settings import SAMPLE_DIR
from app.store import Document
from app.validation import CheckContext, run_checks
from tests.conftest import by_file, sample_source, truth, wait_for_batch
from tests.fakes import Recorder, anthropic_client, claude_message, json_response

SAMPLES = {
    "13-eastgate-lumber-hardware-photo": ("Eastgate Lumber and Hardware", 518.33),
    "14-trailhead-fuel-and-go-photo": ("Trailhead Fuel and Go", 121.64),
    "15-kestrel-equipment-rentals-photo": ("Kestrel Equipment Rentals", 489.06),
}


async def extract(stem: str):
    src = sample_source(f"{stem}.jpg")
    raw = await MockProvider().extract(src, RECEIPT)
    return raw, normalize(raw, RECEIPT)


async def test_mock_reads_the_three_samples_correctly():
    for stem, (merchant, total) in SAMPLES.items():
        _, ex = await extract(stem)
        t = truth(stem)
        assert ex.value("merchant_name") == merchant
        assert ex.money("total") == total
        assert ex.value("currency") == "CAD"
        assert ex.value("date") == t["fields"]["date"]["value"]
        assert [li.description for li in ex.line_items] == [
            li["description"] for li in t["line_items"]
        ]
        assert [li.amount for li in ex.line_items] == [li["amount"] for li in t["line_items"]]
        # Photos carry highlight boxes for the review screen.
        assert ex.field("total").source.quote and ex.line_items[0].source.quote


async def test_mock_suggests_the_expected_categories():
    for stem in SAMPLES:
        _, ex = await extract(stem)
        expected = truth(stem)["expected_categories"]
        assert [li.category for li in ex.line_items] == expected["lines"]
        assert ex.category == expected["receipt"]
        assert all(li.category_reason for li in ex.line_items) and ex.category_reason


async def test_math_checks_pass_on_two_samples_and_flag_the_misprinted_tax():
    results = {}
    for stem in SAMPLES:
        _, ex = await extract(stem)
        results[stem] = {c.id: c for c in run_checks(ex, CheckContext())}
    for stem in list(SAMPLES)[:2]:
        assert results[stem]["totals"].status == "pass"
        assert results[stem]["line_items_sum"].status == "pass"
        assert results[stem]["line_math"].status == "pass"
    bad = results["15-kestrel-equipment-rentals-photo"]
    assert bad["totals"].status == "fail"
    assert "479.06" in bad["totals"].message and "489.06" in bad["totals"].message
    assert bad["line_items_sum"].status == "pass"


def make_doc(doc_id: str, ex) -> Document:
    return Document(
        id=doc_id,
        batch_id="bat_1",
        position=0,
        filename=f"{doc_id}.jpg",
        media_type="image/jpeg",
        size=1,
        sha256=doc_id,
        status="approved",
        created_at=0,
        updated_at=0,
        doc_type="receipt",
        extraction=ex,
        provider="mock",
    )


async def sample_docs() -> list[Document]:
    return [make_doc(stem[:2], (await extract(stem))[1]) for stem in SAMPLES]


async def test_category_summary_allocates_tax_and_adds_up():
    docs = await sample_docs()
    rows = {r["category"]: r for r in category_summary(docs)}
    assert list(rows) == [
        "Materials and supplies",
        "Vehicle fuel",
        "Equipment rental",
        "Tools",
        "Safety gear and workwear",
        "Meals",
    ]
    # Eastgate: four materials lines of 430.72 of 458.70 before tax, HST 59.63 shared by amount.
    assert rows["Materials and supplies"]["amount_before_tax"] == 430.72
    assert rows["Materials and supplies"]["tax"] == 55.99
    assert rows["Equipment rental"]["amount_before_tax"] == 432.80
    assert rows["Equipment rental"]["tax"] == 46.26  # as printed on the slip
    assert rows["Vehicle fuel"]["receipts"] == 1 and rows["Meals"]["line_items"] == 2
    total = summary_with_total(docs)[-1]
    assert total["category"] == "All categories" and total["receipts"] == 3
    assert total["amount_before_tax"] == round(458.70 + 107.65 + 432.80, 2)
    assert total["tax"] == round(59.63 + 13.99 + 46.26, 2)


async def test_summary_ignores_invoices_and_empty_batches():
    assert summary_with_total([]) == []


async def test_adapter_asks_for_categories_and_returns_them():
    src = sample_source("14-trailhead-fuel-and-go-photo.jpg")
    data = await MockProvider().extract(src, RECEIPT)
    rec = Recorder(json_response(claude_message(data, model="claude-haiku-5-5")))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-haiku-5-5")

    out = await provider.extract(src, RECEIPT)
    assert out["expense_category"]["category"] == "Vehicle fuel"
    assert out["line_items"][1]["category"] == "Meals"
    assert normalize(out, RECEIPT).category == "Vehicle fuel"

    body = rec.body
    schema = body["output_config"]["format"]["schema"]
    assert "expense_category" in schema["properties"]
    assert "Equipment rental" in str(schema)
    prompt = body["messages"][0]["content"][1]["text"]
    assert "bookkeeper or accountant to review" in prompt
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert body["model"] == "claude-haiku-5-5"


# ---- Through the API ----


def start_receipts(client) -> dict:
    created = client.post("/batches/sample-receipts")
    assert created.status_code == 201
    batch = created.json()
    assert batch["mode"] == "receipt" and batch["is_sample"]
    return by_file(wait_for_batch(client, batch["id"])) | {"_id": batch["id"]}


def test_sample_receipts_batch_end_to_end(client):
    docs = start_receipts(client)
    bid = docs.pop("_id")
    assert sorted(docs) == [f"{s}.jpg" for s in SAMPLES]
    kestrel = docs["15-kestrel-equipment-rentals-photo.jpg"]
    assert kestrel["status"] == "needs_review" and kestrel["issues"]["fail"] == 1
    assert kestrel["category"] == "Equipment rental"
    assert docs["13-eastgate-lumber-hardware-photo.jpg"]["status"] == "ready"
    assert all(d["demo"] for d in docs.values())

    listing = client.get("/samples/receipts").json()["documents"]
    assert [d["file"] for d in listing] == [f"{s}.jpg" for s in SAMPLES]
    assert client.get(listing[0]["url"]).headers["content-type"] == "image/jpeg"

    # Edit a line's category and the job tag; both stick, and checks re-run.
    doc_id = docs["13-eastgate-lumber-hardware-photo.jpg"]["id"]
    detail = client.get(f"/documents/{doc_id}").json()
    lines = detail["extraction"]["line_items"]
    lines[4]["category"] = "Materials and supplies"
    lines[4]["category_reason"] = "Set by you."
    r = client.patch(
        f"/documents/{doc_id}",
        json={"line_items": lines, "category": "Tools", "job": "  Maple St   deck  "},
    )
    assert r.status_code == 200
    ex = r.json()["extraction"]
    assert ex["line_items"][4]["category"] == "Materials and supplies"
    assert (ex["category"], ex["category_edited"], ex["job"]) == ("Tools", True, "Maple St deck")
    assert r.json()["job"] == "Maple St deck"
    # A made-up category is refused, and an empty job clears the tag.
    assert client.patch(f"/documents/{doc_id}", json={"category": "Write-off"}).status_code == 422
    cleared = client.patch(f"/documents/{doc_id}", json={"job": ""}).json()
    assert cleared["extraction"]["job"] is None

    # Exports carry the category column and the per-category summary.
    client.post(f"/batches/{bid}/approve-ready")
    rows = list(
        csv.DictReader(
            io.StringIO(client.get(f"/batches/{bid}/export?format=csv&scope=all").text.lstrip("﻿"))
        )
    )
    by_name = {r["file"]: r for r in rows}
    assert by_name["14-trailhead-fuel-and-go-photo.jpg"]["category"] == "Vehicle fuel"
    assert by_name["13-eastgate-lumber-hardware-photo.jpg"]["category"] == "Tools"
    summary = client.get(f"/batches/{bid}/export?format=csv-categories&scope=all")
    assert "by-category" in summary.headers["content-disposition"]
    cats = list(csv.DictReader(io.StringIO(summary.text.lstrip("﻿"))))
    assert cats[-1]["category"] == "All categories"
    xlsx = client.get(f"/batches/{bid}/export?format=xlsx&scope=all")
    wb = load_workbook(io.BytesIO(xlsx.content))
    ws = wb["By category"]
    assert [c.value for c in ws[1]][:2] == ["Category", "Receipts"]
    notes = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert any("bookkeeper or accountant to review" in n for n in notes)
    assert "Category" in [c.value for c in wb["Line items"][1]]


def test_invoice_exports_have_no_category_columns(client):
    data = (SAMPLE_DIR / "documents" / "01-northpeak-office-supply.pdf").read_bytes()
    bid = client.post("/batches", json={"mode": "invoice"}).json()["id"]
    client.post(f"/batches/{bid}/documents", files=[("files", ("a.pdf", data, "application/pdf"))])
    wait_for_batch(client, bid)
    header = client.get(f"/batches/{bid}/export?format=csv&scope=all").text.splitlines()[0]
    assert "category" not in header
    wb = load_workbook(
        io.BytesIO(client.get(f"/batches/{bid}/export?format=xlsx&scope=all").content)
    )
    assert "By category" not in wb.sheetnames
