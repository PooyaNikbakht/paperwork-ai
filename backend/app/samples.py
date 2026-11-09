"""The bundled sample documents and their manifest."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.settings import SAMPLE_DIR


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / "manifest.json").read_text())


def sample_path(filename: str) -> Path:
    return SAMPLE_DIR / "documents" / filename


@lru_cache(maxsize=1)
def load_receipts_manifest() -> dict[str, Any]:
    """The Receipts-mode samples: three phone photos of job receipts."""
    return json.loads((SAMPLE_DIR / "receipts_manifest.json").read_text())


def find_sample(filename: str) -> dict[str, Any] | None:
    entries = [*load_manifest()["documents"], *load_receipts_manifest()["documents"]]
    return next((d for d in entries if d["file"] == filename), None)
