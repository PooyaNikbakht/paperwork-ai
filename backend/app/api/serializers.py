"""Response shapes for the API."""

from typing import Any

from app.models import Extraction
from app.store import Batch, Document

PARTY = {"invoice": "vendor_name", "receipt": "merchant_name"}
DATE = {"invoice": "invoice_date", "receipt": "date", "custom": "date"}


def headline(ex: Extraction | None) -> dict[str, Any]:
    """The few values shown in the batch table."""
    if ex is None:
        return {
            "party": None,
            "number": None,
            "date": None,
            "currency": None,
            "total": None,
            "category": None,
            "job": None,
        }
    party = ex.value(PARTY.get(ex.doc_type, ""))
    if party is None and ex.doc_type == "custom" and ex.fields:
        party = ex.fields[0].value
    date = ex.value(DATE.get(ex.doc_type, ""))
    if date is None:
        date = next((f.value for f in ex.fields if f.type == "date" and f.value), None)
    total = ex.money("total")
    if total is None and ex.doc_type == "custom":
        total = next(
            (f.value for f in ex.fields if f.type == "money" and f.value is not None), None
        )
    return {
        "party": party,
        "number": ex.value("invoice_number"),
        "date": date,
        "currency": ex.value("currency"),
        "total": total,
        "category": ex.category,
        "job": ex.job,
    }


def doc_summary(doc: Document) -> dict[str, Any]:
    fails = [c for c in doc.checks if c.status == "fail"]
    warns = [c for c in doc.checks if c.status == "warn"]
    top = (fails or warns or [None])[0]
    return {
        "id": doc.id,
        "batch_id": doc.batch_id,
        "position": doc.position,
        "filename": doc.filename,
        "media_type": doc.media_type,
        "size": doc.size,
        "status": doc.status,
        "doc_type": doc.doc_type,
        "page_count": doc.page_count,
        **headline(doc.extraction),
        "issues": {"fail": len(fails), "warn": len(warns)},
        "top_issue": {"label": top.label, "message": top.message, "status": top.status}
        if top
        else None,
        "provider": doc.provider,
        "demo": doc.provider == "mock",
        "error": doc.error,
        "approved_at": doc.approved_at,
        "updated_at": doc.updated_at,
    }


def batch_out(batch: Batch, docs: list[Document]) -> dict[str, Any]:
    return {
        "id": batch.id,
        "created_at": batch.created_at,
        "mode": batch.mode,
        "is_sample": batch.is_sample,
        "custom_fields": [f.model_dump() for f in batch.custom_fields]
        if batch.custom_fields
        else None,
        "documents": [doc_summary(d) for d in docs],
    }


def document_out(doc: Document) -> dict[str, Any]:
    return {
        **doc_summary(doc),
        "model": doc.model,
        "demo_reason": doc.demo_reason,
        "has_text_layer": doc.has_text_layer,
        "pages": [
            {"number": i + 1, "width": w, "height": h, "url": f"/documents/{doc.id}/pages/{i + 1}"}
            for i, (w, h) in enumerate(doc.page_sizes)
        ],
        "extraction": doc.extraction.model_dump() if doc.extraction else None,
        "checks": [c.model_dump() for c in doc.checks],
    }
