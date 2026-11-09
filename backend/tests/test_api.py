import io
import json

from openpyxl import load_workbook

from app.models import DocSpec, DocType
from app.providers.base import ProviderError, SourceFile
from tests.conftest import by_file, make_client, sample_bytes, wait_for_batch


def sample_batch(client):
    batch = client.post("/batches/sample").json()
    return wait_for_batch(client, batch["id"])


def test_health_and_config(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "provider": "mock",
        "model": None,
        "demo_mode": True,
    }
    cfg = client.get("/config").json()
    assert cfg["demo_mode"] is True
    assert cfg["limits"]["max_pages"] == 30


def test_samples_listed_and_downloadable(client):
    samples = client.get("/samples").json()
    assert len(samples["documents"]) == 12
    assert samples["custom_fields"][0]["key"] == "customer_name"
    r = client.get("/samples/01-northpeak-office-supply.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/samples/../../app/main.py").status_code == 404


def test_sample_batch_statuses_and_flags(client):
    docs = by_file(sample_batch(client))
    assert len(docs) == 12
    ready = {f for f, d in docs.items() if d["status"] == "ready"}
    assert ready == {
        "01-northpeak-office-supply.pdf",
        "02-cedar-pine-packaging.pdf",
        "03-maple-ridge-flour-mill.pdf",
        "08-greenleaf-market-receipt.pdf",
        "10-atelier-lumiere-design.pdf",
    }
    flagged = {f: d["top_issue"]["label"] for f, d in docs.items() if d["issues"]["fail"]}
    assert flagged == {
        "04-bluewater-print-shop.pdf": "Line items add up",
        "05-northpeak-office-supply-resent.pdf": "Duplicates",
        "06-lakeshore-cleaning-scan.png": "Line math",
        "09-summit-cloud-hosting.pdf": "Currency",
        "11-riverbend-courier.pdf": "Totals add up",
    }
    assert docs["12-catering-order-form.pdf"]["doc_type"] == "custom"
    assert docs["12-catering-order-form.pdf"]["party"] == "Priya Raman"
    assert all(d["demo"] for d in docs.values())


def test_document_detail_has_pages_sources_and_checks(client):
    docs = by_file(sample_batch(client))
    doc = client.get(f"/documents/{docs['03-maple-ridge-flour-mill.pdf']['id']}").json()
    assert len(doc["pages"]) == 2
    assert doc["has_text_layer"] is True
    total = next(f for f in doc["extraction"]["fields"] if f["key"] == "total")
    assert (
        total["source"]["page"] == 2
        and total["source"]["found"] is True
        and total["source"]["boxes"]
    )
    assert len(doc["extraction"]["line_items"]) == 28
    assert {c["id"] for c in doc["checks"]} >= {"line_items_sum", "totals", "duplicate", "sources"}
    page = client.get(doc["pages"][1]["url"])
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert client.get(f"/documents/{doc['id']}/pages/9").status_code == 404
    original = client.get(f"/documents/{doc['id']}/file")
    assert original.content == sample_bytes("03-maple-ridge-flour-mill.pdf")


def test_fixing_a_misread_turns_the_checks_green(client):
    docs = by_file(sample_batch(client))
    doc_id = docs["06-lakeshore-cleaning-scan.png"]["id"]
    doc = client.get(f"/documents/{doc_id}").json()
    lines = doc["extraction"]["line_items"]
    lines[2] = {**lines[2], "amount": 1280.0, "edited": True}
    r = client.patch(
        f"/documents/{doc_id}",
        json={"line_items": lines, "fields": {"vendor_tax_number": "79912 3348 RT0001"}},
    )
    assert r.status_code == 200
    out = r.json()
    statuses = {c["id"]: c["status"] for c in out["checks"]}
    assert statuses["line_math"] == "pass"
    assert statuses["line_items_sum"] == "pass"
    assert statuses["confidence"] == "pass"
    assert out["status"] == "ready"
    field = next(f for f in out["extraction"]["fields"] if f["key"] == "vendor_tax_number")
    assert field["edited"] is True and field["original"] == "79912 3348 RT0007"


def test_edit_validation_errors(client):
    docs = by_file(sample_batch(client))
    doc_id = docs["01-northpeak-office-supply.pdf"]["id"]
    assert client.patch(f"/documents/{doc_id}", json={"fields": {"nope": 1}}).status_code == 422
    r = client.patch(f"/documents/{doc_id}", json={"fields": {"total": "lots"}})
    assert r.status_code == 422 and "number" in r.json()["error"]["message"]


def test_approve_requires_acknowledging_failed_checks(client):
    docs = by_file(sample_batch(client))
    doc_id = docs["11-riverbend-courier.pdf"]["id"]
    r = client.post(f"/documents/{doc_id}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_failed_checks"
    r = client.post(f"/documents/{doc_id}/approve", json={"acknowledge": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # Approved documents are locked until reopened.
    assert (
        client.patch(f"/documents/{doc_id}", json={"fields": {"total": 254.25}}).status_code == 409
    )
    r = client.post(f"/documents/{doc_id}/reopen")
    assert r.json()["status"] == "needs_review"
    r = client.patch(f"/documents/{doc_id}", json={"fields": {"total": 254.25}})
    assert {c["id"]: c["status"] for c in r.json()["checks"]}["totals"] == "pass"


def test_duplicate_follows_the_first_copy(client):
    docs = by_file(sample_batch(client))
    first = docs["01-northpeak-office-supply.pdf"]["id"]
    second = docs["05-northpeak-office-supply-resent.pdf"]["id"]
    # Changing the first copy's number clears the duplicate flag on the second.
    client.patch(f"/documents/{first}", json={"fields": {"invoice_number": "NP-24818"}})
    second_doc = client.get(f"/documents/{second}").json()
    assert {c["id"]: c["status"] for c in second_doc["checks"]}["duplicate"] == "pass"
    client.patch(f"/documents/{first}", json={"fields": {"invoice_number": "NP-24817"}})
    second_doc = client.get(f"/documents/{second}").json()
    assert {c["id"]: c["status"] for c in second_doc["checks"]}["duplicate"] == "fail"


def test_duplicates_across_batches_only_when_approved(client):
    files = {"files": ("a.pdf", sample_bytes("01-northpeak-office-supply.pdf"), "application/pdf")}

    def upload():
        bid = client.post("/batches", json={"mode": "auto"}).json()["id"]
        client.post(f"/batches/{bid}/documents", files=files)
        return wait_for_batch(client, bid)["documents"][0]

    first = upload()
    assert upload()["status"] == "ready"  # not approved yet, so no clash
    client.post(f"/documents/{first['id']}/approve")
    doc = upload()
    assert doc["top_issue"]["label"] == "Duplicates"
    assert "already approved" in doc["top_issue"]["message"]


def test_sample_batches_never_collide_across_batches(client):
    first = by_file(sample_batch(client))
    client.post(f"/documents/{first['01-northpeak-office-supply.pdf']['id']}/approve")
    again = by_file(sample_batch(client))
    assert again["01-northpeak-office-supply.pdf"]["status"] == "ready"


def test_approve_ready_and_exports(client):
    batch = sample_batch(client)
    bid = batch["id"]
    assert client.get(f"/batches/{bid}/export?format=csv").status_code == 409
    after = client.post(f"/batches/{bid}/approve-ready").json()
    assert sum(d["status"] == "approved" for d in after["documents"]) == 5

    csv = client.get(f"/batches/{bid}/export?format=csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert 'filename="paperwork-' in csv.headers["content-disposition"]
    text = csv.content.decode("utf-8-sig")
    assert text.count("\r\n") == 6  # header + 5 approved
    assert "Northpeak Office Supply Ltd.,NP-24817,2026-09-14" in text

    lines = client.get(f"/batches/{bid}/export?format=csv-lines").content.decode("utf-8-sig")
    assert "Unbleached bread flour, 20 kg" in lines

    sheets = client.get(f"/batches/{bid}/export?format=sheets&scope=all").content
    assert not sheets.startswith(b"\xef\xbb\xbf")

    xlsx = client.get(f"/batches/{bid}/export?format=xlsx&scope=all")
    wb = load_workbook(io.BytesIO(xlsx.content))
    assert wb.sheetnames == ["Documents", "Line items", "Taxes", "Checks", "By category"]
    assert wb["Documents"].max_row == 13

    data = json.loads(client.get(f"/batches/{bid}/export?format=json").content)
    assert len(data["documents"]) == 5
    assert data["documents"][0]["extraction"]["fields"][0]["source"]["quote"]


def test_upload_validation(settings):
    settings.max_upload_mb = 1
    settings.max_pages = 1
    settings.max_files_per_batch = 2
    with make_client(settings) as client:
        bid = client.post("/batches", json={}).json()["id"]
        url = f"/batches/{bid}/documents"
        r = client.post(url, files={"files": ("notes.pdf", b"hello there", "application/pdf")})
        assert r.status_code == 415
        r = client.post(
            url, files={"files": ("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * 1_100_000, "image/png")}
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
        r = client.post(
            url,
            files={
                "files": (
                    "two.pdf",
                    sample_bytes("03-maple-ridge-flour-mill.pdf"),
                    "application/pdf",
                )
            },
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "too_many_pages"
        three = [
            (
                "files",
                (f"{i}.pdf", sample_bytes("01-northpeak-office-supply.pdf"), "application/pdf"),
            )
            for i in range(3)
        ]
        assert client.post(url, files=three).json()["error"]["code"] == "too_many_files"
        assert client.get("/batches/bat_missing").status_code == 404


def test_custom_mode_needs_fields(client):
    r = client.post("/batches", json={"mode": "custom"})
    assert r.status_code == 422
    fields = [{"key": "name", "label": "Name"}, {"key": "name", "label": "Again"}]
    assert (
        client.post("/batches", json={"mode": "custom", "custom_fields": fields}).status_code == 422
    )
    fields = [{"key": "Bad Key!", "label": "x"}]
    assert (
        client.post("/batches", json={"mode": "custom", "custom_fields": fields}).status_code == 422
    )


def test_custom_mode_extracts_user_fields(client):
    fields = [
        {"key": "customer_name", "label": "Customer name", "required": True},
        {"key": "budget", "label": "Budget", "type": "money"},
        {"key": "favourite_colour", "label": "Favourite colour"},
    ]
    bid = client.post("/batches", json={"mode": "custom", "custom_fields": fields}).json()["id"]
    client.post(
        f"/batches/{bid}/documents",
        files={
            "files": ("form.pdf", sample_bytes("12-catering-order-form.pdf"), "application/pdf")
        },
    )
    doc = wait_for_batch(client, bid)["documents"][0]
    detail = client.get(f"/documents/{doc['id']}").json()
    values = {f["key"]: f["value"] for f in detail["extraction"]["fields"]}
    assert values == {"customer_name": "Priya Raman", "budget": 450.0, "favourite_colour": None}


def test_reextract_as_another_type(client):
    docs = by_file(sample_batch(client))
    doc_id = docs["08-greenleaf-market-receipt.pdf"]["id"]
    r = client.post(f"/documents/{doc_id}/reextract", json={"doc_type": "invoice"})
    assert r.status_code == 202
    batch = wait_for_batch(client, docs["08-greenleaf-market-receipt.pdf"]["batch_id"])
    doc = by_file(batch)["08-greenleaf-market-receipt.pdf"]
    assert doc["doc_type"] == "invoice"
    assert doc["status"] == "needs_review"  # an invoice spec on a receipt is missing fields


def test_delete_batch(client):
    batch = sample_batch(client)
    assert client.delete(f"/batches/{batch['id']}").status_code == 204
    assert client.get(f"/batches/{batch['id']}").status_code == 404


def test_batch_rate_limit(settings):
    settings.batches_per_ip_per_hour = 2
    with make_client(settings) as client:
        assert client.post("/batches", json={}).status_code == 201
        assert client.post("/batches/sample").status_code == 201
        r = client.post("/batches", json={})
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


class FailingProvider:
    name = "anthropic"
    model = "claude-opus-5-5"

    def __init__(self, error: ProviderError) -> None:
        self.error = error

    async def classify(self, doc: SourceFile) -> DocType:
        raise self.error

    async def extract(self, doc: SourceFile, spec: DocSpec) -> dict:
        raise self.error


def test_provider_errors_fall_back_to_demo_mode(settings):
    provider = FailingProvider(ProviderError("provider_busy", "Claude is busy right now."))
    with make_client(settings, provider) as client:
        bid = client.post("/batches", json={"mode": "invoice"}).json()["id"]
        client.post(
            f"/batches/{bid}/documents",
            files={
                "files": (
                    "a.pdf",
                    sample_bytes("01-northpeak-office-supply.pdf"),
                    "application/pdf",
                )
            },
        )
        doc = wait_for_batch(client, bid)["documents"][0]
        assert doc["status"] == "ready" and doc["demo"] is True
        detail = client.get(f"/documents/{doc['id']}").json()
        assert detail["demo_reason"].startswith("Claude is busy right now.")


def test_refusals_fail_the_document(settings):
    provider = FailingProvider(
        ProviderError("refused", "Claude declined to read this document.", fallback_ok=False)
    )
    with make_client(settings, provider) as client:
        bid = client.post("/batches", json={"mode": "invoice"}).json()["id"]
        client.post(
            f"/batches/{bid}/documents",
            files={
                "files": (
                    "a.pdf",
                    sample_bytes("01-northpeak-office-supply.pdf"),
                    "application/pdf",
                )
            },
        )
        doc = wait_for_batch(client, bid)["documents"][0]
        assert doc["status"] == "failed"
        assert doc["error"] == "Claude declined to read this document."


class RecordingProvider(FailingProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, doc):
        return "invoice"

    async def extract(self, doc, spec):
        from app.providers.mock import MockProvider

        self.calls += 1
        return await MockProvider().extract(doc, spec)


def test_live_quota_and_public_samples_use_demo_mode(settings):
    settings.live_docs_per_ip_per_hour = 1
    settings.sample_provider = "mock"
    provider = RecordingProvider()
    with make_client(settings, provider) as client:
        bid = client.post("/batches", json={"mode": "invoice"}).json()["id"]
        files = [
            ("files", (f"{i}.pdf", sample_bytes("02-cedar-pine-packaging.pdf"), "application/pdf"))
            for i in range(2)
        ]
        client.post(f"/batches/{bid}/documents", files=files)
        docs = wait_for_batch(client, bid)["documents"]
        assert sorted(d["demo"] for d in docs) == [False, True]
        assert provider.calls == 1
        sample = wait_for_batch(client, client.post("/batches/sample").json()["id"])
        assert all(d["demo"] for d in sample["documents"])
        assert provider.calls == 1


def test_public_demo_preset():
    from app.settings import Settings

    s = Settings(_env_file=None, public_demo=True, max_pages=4)
    assert s.max_upload_mb == 10 and s.max_pages == 4 and s.data_ttl_seconds == 3600
    assert s.sample_provider == "mock" and s.dedupe_across_batches is False
