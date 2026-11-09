"""The extraction pipeline: background tasks that read each document, extract, locate and check.

Status flow: queued -> extracting -> needs_review | ready -> approved (or failed).
"""

import asyncio
import logging
from collections import defaultdict

from app.extraction import locate_sources, normalize
from app.limits import LiveQuota
from app.models import DocType, Extraction, spec_for
from app.pages import UnreadableFile, normalized_image, parse_file
from app.providers.base import Extractor, ProviderError, SourceFile
from app.providers.mock import MockProvider
from app.settings import Settings
from app.store import Batch, Document, Store
from app.validation import CheckContext, DuplicateHit, run_checks, status_for
from app.values import norm_key, vendor_key

logger = logging.getLogger(__name__)


class Events:
    """Wakes up SSE listeners when anything in a batch changes."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[None]]] = defaultdict(set)

    def subscribe(self, batch_id: str) -> asyncio.Queue[None]:
        q: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subs[batch_id].add(q)
        return q

    def unsubscribe(self, batch_id: str, q: asyncio.Queue[None]) -> None:
        self._subs[batch_id].discard(q)
        if not self._subs[batch_id]:
            del self._subs[batch_id]

    def publish(self, batch_id: str) -> None:
        for q in list(self._subs.get(batch_id, ())):
            if q.empty():
                q.put_nowait(None)


def dup_key_for(ex: Extraction | None) -> str | None:
    if ex is None or ex.doc_type != "invoice":
        return None
    vendor, number = (
        vendor_key(str(ex.value("vendor_name") or "")),
        norm_key(str(ex.value("invoice_number") or "")),
    )
    return f"{vendor}|{number}" if vendor and number else None


class Pipeline:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        active: Extractor,
        mock: MockProvider,
        quota: LiveQuota,
        events: Events,
    ) -> None:
        self.store = store
        self.settings = settings
        self.active = active
        self.mock = mock
        self.quota = quota
        self.events = events
        self._sem = asyncio.Semaphore(max(1, settings.extraction_concurrency))
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- scheduling ----

    def enqueue(self, doc_id: str, doc_type: DocType | None = None) -> None:
        task = asyncio.create_task(self._run(doc_id, doc_type))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for every running task (tests and evals)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def resume(self) -> None:
        """Re-queue documents left mid-flight by a restart."""
        for doc in self.store.documents_with_status("queued", "extracting"):
            self.enqueue(doc.id)

    # ---- one document ----

    def _choose(self, batch: Batch) -> tuple[Extractor, str | None]:
        if self.active.name == "mock":
            return self.mock, None
        if batch.is_sample and self.settings.sample_provider == "mock":
            return self.mock, "Sample documents run in demo mode on the public demo."
        reason = self.quota.take(batch.client_ip)
        if reason:
            return self.mock, reason
        return self.active, None

    async def _prepare(self, doc: Document) -> Document:
        """Render page images and read the text layer, once per document."""
        if doc.page_count:
            return doc
        data = self.store.read_original(doc)
        parsed = await asyncio.to_thread(parse_file, data, doc.media_type)
        folder = self.store.doc_dir(doc)
        for i, page in enumerate(parsed.pages, start=1):
            ext = "png" if page.image_type == "image/png" else "jpg"
            (folder / f"page-{i}.{ext}").write_bytes(page.image)
        self.store.update_document(
            doc.id,
            page_count=parsed.page_count,
            page_sizes=[[p.width, p.height] for p in parsed.pages],
            page_texts=parsed.texts,
        )
        refreshed = self.store.get_document(doc.id)
        assert refreshed is not None
        return refreshed

    def _source_file(self, doc: Document) -> SourceFile:
        data = self.store.read_original(doc)
        media = doc.media_type
        if media != "application/pdf":
            data, media = normalized_image(data)
        return SourceFile(
            data=data,
            media_type=media,
            filename=doc.filename,
            sha256=doc.sha256,
            page_count=doc.page_count,
            texts=doc.page_texts,
        )

    async def _run(self, doc_id: str, forced_type: DocType | None) -> None:
        async with self._sem:
            doc = self.store.get_document(doc_id)
            batch = self.store.get_batch(doc.batch_id) if doc else None
            if doc is None or batch is None:
                return
            self.store.update_document(doc_id, status="extracting", error=None)
            self.events.publish(batch.id)
            old_key = doc.dup_key
            try:
                doc = await self._prepare(doc)
                src = self._source_file(doc)
                provider, demo_reason = self._choose(batch)
                try:
                    doc_type = forced_type or await self._doc_type(provider, batch, src)
                    spec = spec_for(doc_type, batch.custom_fields)
                    raw = await provider.extract(src, spec)
                except ProviderError as exc:
                    if not (
                        exc.fallback_ok
                        and self.settings.fallback_to_mock
                        and provider is not self.mock
                    ):
                        raise
                    logger.warning("Provider failed (%s); using demo mode", exc.code)
                    provider = self.mock
                    demo_reason = f"{exc.message} This document used demo mode instead."
                    doc_type = forced_type or await self._doc_type(provider, batch, src)
                    spec = spec_for(doc_type, batch.custom_fields)
                    raw = await provider.extract(src, spec)

                ex = normalize(raw, spec)
                pdf = src.data if src.is_pdf else None
                await asyncio.to_thread(locate_sources, ex, pdf, doc.has_text_layer)
                self.store.update_document(
                    doc_id,
                    doc_type=doc_type,
                    extraction=ex,
                    provider=provider.name,
                    model=provider.model,
                    demo_reason=demo_reason,
                    dup_key=dup_key_for(ex),
                    approved_at=None,
                )
                self.revalidate(doc_id, force_status=True)
                self.refresh_duplicates({old_key, dup_key_for(ex)}, skip=doc_id)
            except (ProviderError, UnreadableFile) as exc:
                message = exc.message if isinstance(exc, ProviderError) else str(exc)
                self.store.update_document(doc_id, status="failed", error=message)
            except Exception:
                logger.exception("Extraction failed for %s", doc_id)
                self.store.update_document(
                    doc_id, status="failed", error="Something went wrong reading this document."
                )
            self.events.publish(batch.id)

    async def _doc_type(self, provider: Extractor, batch: Batch, src: SourceFile) -> DocType:
        if batch.mode != "auto":
            return batch.mode
        return await provider.classify(src)

    # ---- checks ----

    def context_for(self, doc: Document) -> CheckContext:
        return CheckContext(
            page_texts=doc.page_texts,
            has_text_layer=doc.has_text_layer,
            duplicates=self.duplicates_of(doc),
            low_confidence=self.settings.low_confidence,
        )

    def duplicates_of(self, doc: Document) -> list[DuplicateHit]:
        if not doc.dup_key:
            return []
        hits = []
        for other in self.store.find_by_dup_key(doc.dup_key):
            if other.id == doc.id or other.status == "failed":
                continue
            if other.batch_id == doc.batch_id:
                if other.position < doc.position:
                    hits.append(
                        DuplicateHit(other.id, other.filename, True, other.status == "approved")
                    )
            elif (
                self.settings.dedupe_across_batches
                and other.status == "approved"
                and not self._is_sample(doc.batch_id)
                and not self._is_sample(other.batch_id)
            ):
                hits.append(DuplicateHit(other.id, other.filename, False, True))
        return hits

    def _is_sample(self, batch_id: str) -> bool:
        """Sample batches are re-run by everyone, so they never count as duplicates elsewhere."""
        batch = self.store.get_batch(batch_id)
        return bool(batch and batch.is_sample)

    def revalidate(self, doc_id: str, *, force_status: bool = False) -> Document | None:
        doc = self.store.get_document(doc_id)
        if doc is None or doc.extraction is None:
            return doc
        checks = run_checks(doc.extraction, self.context_for(doc))
        status = doc.status
        if force_status or status in ("needs_review", "ready"):
            status = status_for(checks)
        self.store.update_document(doc_id, checks=checks, status=status)
        return self.store.get_document(doc_id)

    def refresh_duplicates(self, keys: set[str | None], skip: str | None = None) -> None:
        for key in keys:
            if not key:
                continue
            for other in self.store.find_by_dup_key(key):
                if other.id != skip and other.status in ("needs_review", "ready", "approved"):
                    self.revalidate(other.id)
