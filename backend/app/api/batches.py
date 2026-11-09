"""Batch routes: create, upload, watch, approve, export."""

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import Services, Svc, client_ip, require_batch
from app.api.serializers import batch_out
from app.errors import AppError
from app.exports import EXTENSION, MEDIA, ExportFormat, export, summary_with_total
from app.models import BatchMode, FieldSpec
from app.pages import UnreadableFile, count_pages, sniff
from app.samples import load_manifest, load_receipts_manifest, sample_path

router = APIRouter(tags=["batches"])


class BatchIn(BaseModel):
    mode: BatchMode = "auto"
    custom_fields: list[FieldSpec] | None = Field(default=None, max_length=25)


def _check_batch_quota(services: Services, request: Request) -> str:
    ip = client_ip(request, services.settings.trust_proxy_headers)
    if not services.batch_limiter.hit(ip):
        raise AppError(
            429,
            "rate_limited",
            "You've started a lot of batches in the last hour. Please try again later.",
        )
    return ip


def _validate_fields(fields: list[FieldSpec] | None) -> None:
    if fields:
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise AppError(422, "validation_error", "Each custom field needs a different name.")


@router.post("/batches", status_code=201)
async def create_batch(body: BatchIn, request: Request, services: Svc) -> dict:
    _validate_fields(body.custom_fields)
    if body.mode == "custom" and not body.custom_fields:
        raise AppError(422, "validation_error", "Add at least one field for custom-fields mode.")
    ip = _check_batch_quota(services, request)
    batch = services.store.create_batch(body.mode, body.custom_fields, client_ip=ip)
    return batch_out(batch, [])


@router.post("/batches/sample", status_code=201)
async def create_sample_batch(request: Request, services: Svc) -> dict:
    """A batch preloaded with the bundled sample documents."""
    ip = _check_batch_quota(services, request)
    manifest = load_manifest()
    fields = [FieldSpec(**f) for f in manifest["custom_fields"]]
    batch = services.store.create_batch("auto", fields, is_sample=True, client_ip=ip)
    for entry in manifest["documents"]:
        data = sample_path(entry["file"]).read_bytes()
        doc = services.store.add_document(
            batch.id, entry["file"], entry["media_type"], data, hashlib.sha256(data).hexdigest()
        )
        services.pipeline.enqueue(doc.id)
    services.events.publish(batch.id)
    return batch_out(batch, services.store.list_documents(batch.id))


@router.post("/batches/sample-receipts", status_code=201)
async def create_sample_receipts_batch(request: Request, services: Svc) -> dict:
    """A Receipts-mode batch preloaded with three sample job receipts."""
    ip = _check_batch_quota(services, request)
    batch = services.store.create_batch("receipt", None, is_sample=True, client_ip=ip)
    for entry in load_receipts_manifest()["documents"]:
        data = sample_path(entry["file"]).read_bytes()
        doc = services.store.add_document(
            batch.id, entry["file"], entry["media_type"], data, hashlib.sha256(data).hexdigest()
        )
        services.pipeline.enqueue(doc.id)
    services.events.publish(batch.id)
    return batch_out(batch, services.store.list_documents(batch.id))


_SAFE_NAME = re.compile(r"[^\w.\- ()]+")


def _clean_name(name: str | None) -> str:
    base = (name or "document").replace("\\", "/").split("/")[-1]
    return _SAFE_NAME.sub("_", base).strip()[:120] or "document"


@router.post("/batches/{batch_id}/documents", status_code=201)
async def upload_documents(
    batch_id: str,
    services: Svc,
    files: Annotated[list[UploadFile], File(description="PDF, PNG or JPEG files")],
) -> dict:
    s = services.settings
    batch = require_batch(services, batch_id)
    existing = len(services.store.list_documents(batch_id))
    if not files:
        raise AppError(422, "no_files", "Choose at least one file.")
    if existing + len(files) > s.max_files_per_batch:
        raise AppError(
            413,
            "too_many_files",
            f"A batch can hold up to {s.max_files_per_batch} files.",
        )
    accepted: list[tuple[str, str, bytes]] = []
    for upload in files:
        name = _clean_name(upload.filename)
        data = await upload.read(s.max_upload_bytes + 1)
        if len(data) > s.max_upload_bytes:
            raise AppError(413, "file_too_large", f"{name} is larger than {s.max_upload_mb} MB.")
        if not data:
            raise AppError(422, "empty_file", f"{name} is empty.")
        media = sniff(data)
        if media is None:
            raise AppError(415, "unsupported_type", f"{name} isn't a PDF, PNG or JPEG file.")
        try:
            pages = await asyncio.to_thread(count_pages, data, media)
        except UnreadableFile as exc:
            raise AppError(422, "unreadable_file", f"{name}: {exc}") from exc
        if pages > s.max_pages:
            raise AppError(
                413, "too_many_pages", f"{name} has {pages} pages. The limit is {s.max_pages}."
            )
        accepted.append((name, media, data))
    for name, media, data in accepted:
        doc = services.store.add_document(
            batch.id, name, media, data, hashlib.sha256(data).hexdigest()
        )
        services.pipeline.enqueue(doc.id)
    services.events.publish(batch.id)
    return batch_out(batch, services.store.list_documents(batch.id))


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str, services: Svc) -> dict:
    batch = require_batch(services, batch_id)
    return batch_out(batch, services.store.list_documents(batch_id))


@router.get("/batches/{batch_id}/categories")
async def category_totals(batch_id: str, services: Svc) -> dict:
    """Receipt totals per suggested category (the same numbers as the export's summary)."""
    require_batch(services, batch_id)
    docs = [
        d
        for d in services.store.list_documents(batch_id)
        if d.extraction is not None and d.status != "failed"
    ]
    return {"rows": summary_with_total(docs)}


@router.delete("/batches/{batch_id}", status_code=204)
async def delete_batch(batch_id: str, services: Svc) -> Response:
    require_batch(services, batch_id)
    services.store.delete_batch(batch_id)
    services.events.publish(batch_id)
    return Response(status_code=204)


@router.get("/batches/{batch_id}/events")
async def batch_events(batch_id: str, request: Request, services: Svc) -> StreamingResponse:
    """Server-sent events: a `batch` event with the full batch whenever anything changes."""
    require_batch(services, batch_id)

    async def stream() -> AsyncIterator[str]:
        queue = services.events.subscribe(batch_id)
        last = ""
        try:
            yield "retry: 3000\n\n"
            while True:
                batch = services.store.get_batch(batch_id)
                if batch is None:
                    yield "event: gone\ndata: {}\n\n"
                    return
                payload = json.dumps(batch_out(batch, services.store.list_documents(batch_id)))
                if payload != last:
                    yield f"event: batch\ndata: {payload}\n\n"
                    last = payload
                try:
                    await asyncio.wait_for(queue.get(), timeout=15)
                    await asyncio.sleep(0.05)  # coalesce bursts of updates
                except TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected():
                    return
        finally:
            services.events.unsubscribe(batch_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/batches/{batch_id}/approve-ready")
async def approve_ready(batch_id: str, services: Svc) -> dict:
    """Approve every document whose checks all passed."""
    batch = require_batch(services, batch_id)
    now = datetime.now(UTC).timestamp()
    for doc in services.store.list_documents(batch_id):
        if doc.status == "ready":
            services.store.update_document(doc.id, status="approved", approved_at=now)
    services.events.publish(batch_id)
    return batch_out(batch, services.store.list_documents(batch_id))


@router.get("/batches/{batch_id}/export")
async def export_batch(
    batch_id: str,
    services: Svc,
    format: Annotated[ExportFormat, Query()] = "xlsx",
    scope: Annotated[Literal["approved", "all"], Query()] = "approved",
) -> Response:
    require_batch(services, batch_id)
    docs = [d for d in services.store.list_documents(batch_id) if d.extraction is not None]
    if scope == "approved":
        docs = [d for d in docs if d.status == "approved"]
    if not docs:
        message = (
            "Nothing is approved yet. Approve some documents, or export everything."
            if scope == "approved"
            else "No documents have been read yet."
        )
        raise AppError(409, "nothing_to_export", message)
    body = export(format, docs, batch_id)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    suffix = {
        "csv-lines": "-lines",
        "csv-categories": "-by-category",
        "sheets": "-google-sheets",
    }.get(format, "")
    filename = f"paperwork-{stamp}{suffix}.{EXTENSION[format]}"
    return Response(
        content=body,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
