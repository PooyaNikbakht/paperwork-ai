"""Shared services, created once per app and reached through FastAPI dependencies."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.errors import AppError
from app.limits import SlidingWindowLimiter
from app.pipeline import Events, Pipeline
from app.settings import Settings
from app.store import Batch, Document, Store


@dataclass
class Services:
    settings: Settings
    store: Store
    pipeline: Pipeline
    events: Events
    batch_limiter: SlidingWindowLimiter


def get_services(request: Request) -> Services:
    return request.app.state.services


def client_ip(request: Request, trust_proxy: bool) -> str:
    """The caller's IP. Behind a proxy we trust, use the last X-Forwarded-For hop."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


def require_batch(services: Services, batch_id: str) -> Batch:
    batch = services.store.get_batch(batch_id)
    if batch is None:
        raise AppError(404, "batch_not_found", "This batch doesn't exist or has expired.")
    return batch


def require_document(services: Services, doc_id: str) -> Document:
    doc = services.store.get_document(doc_id)
    if doc is None:
        raise AppError(404, "document_not_found", "This document doesn't exist or has expired.")
    return doc


Svc = Annotated[Services, Depends(get_services)]
