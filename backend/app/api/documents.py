"""Document routes: read, page images, edit, approve, reopen, re-extract."""

from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import Svc, require_document
from app.api.serializers import document_out
from app.categories import clean_category
from app.errors import AppError
from app.extraction import coerce
from app.models import DocType, FieldSpec, LineItem, Source, TaxKind, TaxLine, Value
from app.pipeline import dup_key_for

router = APIRouter(tags=["documents"])


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, services: Svc) -> dict:
    return document_out(require_document(services, doc_id))


@router.get("/documents/{doc_id}/pages/{page}")
async def get_page(doc_id: str, page: int, services: Svc) -> FileResponse:
    doc = require_document(services, doc_id)
    path = services.store.page_path(doc, page)
    if path is None:
        raise AppError(404, "page_not_found", "That page isn't available.")
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/documents/{doc_id}/file")
async def get_original(doc_id: str, services: Svc) -> FileResponse:
    doc = require_document(services, doc_id)
    return FileResponse(
        services.store.original_path(doc), media_type=doc.media_type, filename=doc.filename
    )


class LineItemIn(BaseModel):
    description: str = Field(default="", max_length=300)
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: Source | None = None
    edited: bool = True
    category: str | None = Field(default=None, max_length=60)
    category_reason: str = Field(default="", max_length=200)


class TaxIn(BaseModel):
    kind: TaxKind = "Other"
    rate: float | None = None
    amount: float | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: Source | None = None
    edited: bool = True


class DocumentPatch(BaseModel):
    fields: dict[str, str | float | None] | None = None
    line_items: list[LineItemIn] | None = Field(default=None, max_length=500)
    taxes: list[TaxIn] | None = Field(default=None, max_length=20)
    # Receipts: a suggested category the user changed, and the optional job or project tag.
    category: str | None = Field(default=None, max_length=60)
    job: str | None = Field(default=None, max_length=80)


@router.patch("/documents/{doc_id}")
async def edit_document(doc_id: str, body: DocumentPatch, services: Svc) -> dict:
    """Apply corrections and re-run every check."""
    doc = require_document(services, doc_id)
    if doc.extraction is None:
        raise AppError(409, "not_ready", "This document hasn't been read yet.")
    if doc.status == "approved":
        raise AppError(409, "approved", "Reopen this document before editing it.")
    ex = doc.extraction
    for key, raw in (body.fields or {}).items():
        f = ex.field(key)
        if f is None:
            raise AppError(422, "unknown_field", f"There's no field called {key}.")
        if isinstance(raw, str) and len(raw) > 500:
            raise AppError(422, "validation_error", f"{f.label} is too long.")
        value: Value = coerce(FieldSpec(key=f.key, label=f.label, type=f.type), raw)
        if f.type in ("money", "number") and raw not in (None, "") and value is None:
            raise AppError(422, "validation_error", f"{f.label} needs to be a number.")
        f.value = value
        f.edited = value != f.original
    if body.category is not None:
        category = clean_category(body.category)
        if category is None:
            raise AppError(422, "unknown_category", "That isn't one of the expense categories.")
        if category != ex.category:
            ex.category, ex.category_reason, ex.category_edited = category, "Set by you.", True
    if "job" in body.model_fields_set:
        ex.job = " ".join((body.job or "").split()) or None
    if body.line_items is not None:
        lines = []
        for li in body.line_items:
            data = li.model_dump()
            if data["category"] is not None:
                category = clean_category(data["category"])
                if category is None:
                    raise AppError(
                        422, "unknown_category", "That isn't one of the expense categories."
                    )
                data["category"] = category
            lines.append(LineItem(**data))
        ex.line_items = lines
    if body.taxes is not None:
        ex.taxes = [TaxLine(**t.model_dump()) for t in body.taxes]
    old_key = doc.dup_key
    new_key = dup_key_for(ex)
    services.store.update_document(doc_id, extraction=ex, dup_key=new_key)
    services.pipeline.revalidate(doc_id, force_status=True)
    services.pipeline.refresh_duplicates({old_key, new_key}, skip=doc_id)
    services.events.publish(doc.batch_id)
    return document_out(require_document(services, doc_id))


class ApproveIn(BaseModel):
    acknowledge: bool = False


@router.post("/documents/{doc_id}/approve")
async def approve_document(
    doc_id: str,
    services: Svc,
    body: ApproveIn | None = None,
) -> dict:
    doc = require_document(services, doc_id)
    if doc.status not in ("needs_review", "ready"):
        raise AppError(409, "not_reviewable", "Only read documents can be approved.")
    failed = [c for c in doc.checks if c.status == "fail"]
    if failed and not (body and body.acknowledge):
        raise AppError(
            409,
            "has_failed_checks",
            f"{len(failed)} check{'s' if len(failed) > 1 else ''} failed. Fix the values, or "
            "confirm that you want to approve it anyway.",
        )
    services.store.update_document(
        doc_id, status="approved", approved_at=datetime.now(UTC).timestamp()
    )
    services.pipeline.refresh_duplicates({doc.dup_key}, skip=doc_id)
    services.events.publish(doc.batch_id)
    return document_out(require_document(services, doc_id))


@router.post("/documents/{doc_id}/reopen")
async def reopen_document(doc_id: str, services: Svc) -> dict:
    doc = require_document(services, doc_id)
    if doc.status != "approved":
        raise AppError(409, "not_approved", "This document isn't approved.")
    services.store.update_document(doc_id, status="needs_review", approved_at=None)
    services.pipeline.revalidate(doc_id, force_status=True)
    services.pipeline.refresh_duplicates({doc.dup_key}, skip=doc_id)
    services.events.publish(doc.batch_id)
    return document_out(require_document(services, doc_id))


class ReextractIn(BaseModel):
    doc_type: DocType | None = None


@router.post("/documents/{doc_id}/reextract", status_code=202)
async def reextract_document(
    doc_id: str,
    services: Svc,
    body: ReextractIn | None = None,
) -> dict:
    doc = require_document(services, doc_id)
    if doc.status in ("queued", "extracting"):
        raise AppError(409, "busy", "This document is already being read.")
    services.store.update_document(doc_id, status="queued", error=None, approved_at=None)
    services.pipeline.enqueue(doc_id, body.doc_type if body else None)
    services.events.publish(doc.batch_id)
    return document_out(require_document(services, doc_id))
