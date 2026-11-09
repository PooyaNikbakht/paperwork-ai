"""Health, public config for the UI, and the sample documents."""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import Services, Svc
from app.errors import AppError
from app.samples import find_sample, load_manifest, load_receipts_manifest, sample_path

router = APIRouter(tags=["meta"])


def _provider_info(services: Services) -> dict:
    active = services.pipeline.active
    return {"provider": active.name, "model": active.model, "demo_mode": active.name == "mock"}


@router.get("/health")
async def health(services: Svc) -> dict:
    return {"status": "ok", **_provider_info(services)}


@router.get("/config")
async def config(services: Svc) -> dict:
    """What the upload screen needs to know: limits, provider, and the privacy setup."""
    s = services.settings
    return {
        **_provider_info(services),
        "public_demo": s.public_demo,
        "limits": {
            "max_upload_mb": s.max_upload_mb,
            "max_pages": s.max_pages,
            "max_files_per_batch": s.max_files_per_batch,
            "data_ttl_seconds": s.data_ttl_seconds,
        },
        "samples_use_demo_mode": s.sample_provider == "mock"
        or services.pipeline.active.name == "mock",
    }


@router.get("/samples")
async def list_samples() -> dict:
    manifest = load_manifest()
    return {
        "custom_fields": manifest["custom_fields"],
        "documents": [
            {
                "file": d["file"],
                "title": d["title"],
                "scenario": d["scenario"],
                "doc_type": d["doc_type"],
                "expected_checks": d["expected_checks"],
                "url": f"/samples/{d['file']}",
            }
            for d in manifest["documents"]
        ],
    }


@router.get("/samples/receipts")
async def list_receipt_samples() -> dict:
    return {
        "documents": [
            {
                "file": d["file"],
                "title": d["title"],
                "scenario": d["scenario"],
                "expected_checks": d["expected_checks"],
                "url": f"/samples/{d['file']}",
            }
            for d in load_receipts_manifest()["documents"]
        ]
    }


@router.get("/samples/{filename}")
async def get_sample(filename: str) -> FileResponse:
    entry = find_sample(filename)
    if entry is None:
        raise AppError(404, "not_found", "No such sample document.")
    return FileResponse(sample_path(filename), media_type=entry["media_type"], filename=filename)
