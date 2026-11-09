"""FastAPI application factory."""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import batches, documents, meta
from app.api.deps import Services
from app.errors import install_error_handlers
from app.limits import LiveQuota, SlidingWindowLimiter
from app.pipeline import Events, Pipeline
from app.providers import Extractor, build_provider
from app.providers.mock import MockProvider
from app.settings import Settings, get_settings
from app.store import Store

logger = logging.getLogger(__name__)


async def _cleanup_loop(services: Services) -> None:
    """Delete batches older than DATA_TTL_SECONDS, files included."""
    s = services.settings
    while True:
        cutoff = time.time() - s.data_ttl_seconds
        for batch_id in services.store.expired_batches(cutoff):
            services.store.delete_batch(batch_id)
            services.events.publish(batch_id)
            logger.info("Deleted expired batch %s", batch_id)
        await asyncio.sleep(s.cleanup_interval_seconds)


def create_app(settings: Settings | None = None, provider: Extractor | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    store = Store(settings.data_dir)
    events = Events()
    mock = MockProvider(delay_seconds=settings.mock_delay_seconds)
    active = provider or (mock if settings.provider == "mock" else build_provider(settings))
    pipeline = Pipeline(
        store,
        settings,
        active,
        mock,
        LiveQuota(settings.live_docs_per_ip_per_hour, settings.live_docs_per_day),
        events,
    )
    services = Services(
        settings=settings,
        store=store,
        pipeline=pipeline,
        events=events,
        batch_limiter=SlidingWindowLimiter(settings.batches_per_ip_per_hour, 3600),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pipeline.resume()
        cleanup = (
            asyncio.create_task(_cleanup_loop(services)) if settings.data_ttl_seconds > 0 else None
        )
        yield
        if cleanup:
            cleanup.cancel()
        store.close()

    app = FastAPI(
        title="paperwork-ai API",
        version="0.1.0",
        description=(
            "Invoices, receipts and forms in, validated structured data out. Every value comes "
            "with its source on the page, and every document is checked before it's approved."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
        max_age=600,
    )
    install_error_handlers(app)
    app.state.services = services

    app.include_router(meta.router)
    app.include_router(batches.router)
    app.include_router(documents.router)
    return app


app = create_app()
