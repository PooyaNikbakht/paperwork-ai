"""Demo mode: a deterministic, key-free provider.

For the bundled sample documents it replays the generator's ground truth (matched by SHA-256),
with the imperfections listed in sample/demo_quirks.json so the checks have real mistakes to
catch. For any other PDF it falls back to simple text-layer heuristics with low confidence.
"""

import asyncio
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.categories import add_suggestions
from app.models import DocSpec, DocType
from app.providers.base import SourceFile
from app.providers.heuristics import guess_doc_type, heuristic_extract
from app.settings import SAMPLE_DIR, ProviderName


@lru_cache(maxsize=4)
def load_truths(sample_dir: Path = SAMPLE_DIR) -> dict[str, dict[str, Any]]:
    """Ground truth for every sample document, keyed by SHA-256 of the file."""
    out: dict[str, dict[str, Any]] = {}
    truth_dir = sample_dir / "truth"
    if not truth_dir.exists():
        return out
    for path in sorted(truth_dir.glob("*.json")):
        truth = json.loads(path.read_text())
        truth["stem"] = path.stem
        out[truth["sha256"]] = truth
    return out


@lru_cache(maxsize=4)
def load_quirks(sample_dir: Path = SAMPLE_DIR) -> dict[str, dict[str, Any]]:
    path = sample_dir / "demo_quirks.json"
    return json.loads(path.read_text())["documents"] if path.exists() else {}


def _score(stem: str, key: str, low: float, high: float) -> float:
    """A stable pseudo-random confidence in [low, high] for one field of one document."""
    h = int(hashlib.sha256(f"{stem}:{key}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(low + (high - low) * h, 2)


def _source(item: dict[str, Any]) -> dict[str, Any] | None:
    if not item.get("quote"):
        return None
    src: dict[str, Any] = {"page": item["page"], "quote": item["quote"]}
    if item.get("boxes"):
        src["boxes"] = item["boxes"]  # images: where the generator drew it
    return src


def from_truth(truth: dict[str, Any], spec: DocSpec, quirks: dict[str, Any]) -> dict[str, Any]:
    stem = truth["stem"]
    low, high = quirks.get("confidence", [0.93, 0.99])
    overrides = quirks.get("fields", {})
    out: dict[str, Any] = {}
    for f in spec.fields:
        item = truth["fields"].get(f.key)
        if item is None or item.get("value") is None:
            out[f.key] = {"value": None, "confidence": 0.9 if item else 0.0, "source": None}
            continue
        value = item["value"]
        if f.type not in ("money", "number") and value is not None:
            value = str(value)
        entry = {
            "value": value,
            "confidence": _score(stem, f.key, low, high),
            "source": _source(item),
        }
        entry.update(overrides.get(f.key, {}))
        out[f.key] = entry
    if spec.has_lines:
        line_quirks = quirks.get("line_items", {})
        out["line_items"] = []
        for i, item in enumerate(truth.get("line_items", [])):
            line = {
                "description": item["description"],
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "amount": item["amount"],
                "confidence": _score(stem, f"line{i}", low, high),
                "source": _source(item),
            }
            line.update(line_quirks.get(str(i), {}))
            out["line_items"].append(line)
        out["taxes"] = [
            {
                "kind": item["kind"],
                "rate_percent": item["rate"],
                "amount": item["amount"],
                "confidence": _score(stem, f"tax{i}", low, high),
                "source": _source(item),
            }
            for i, item in enumerate(truth.get("taxes", []))
        ]
    return out


class MockProvider:
    name: ProviderName = "mock"
    model: str | None = None

    def __init__(self, delay_seconds: float = 0.0, sample_dir: Path = SAMPLE_DIR) -> None:
        self.delay = delay_seconds
        self.sample_dir = sample_dir

    def truth_for(self, doc: SourceFile) -> dict[str, Any] | None:
        return load_truths(self.sample_dir).get(doc.sha256)

    async def _pause(self, doc: SourceFile, factor: float) -> None:
        if self.delay > 0:
            jitter = int(doc.sha256[:2], 16) / 255 if doc.sha256 else 0.5
            await asyncio.sleep(self.delay * factor * (0.6 + 0.8 * jitter + 0.25 * doc.page_count))

    async def classify(self, doc: SourceFile) -> DocType:
        await self._pause(doc, 0.3)
        truth = self.truth_for(doc)
        if truth:
            return truth["doc_type"]
        return guess_doc_type(doc.texts)

    async def extract(self, doc: SourceFile, spec: DocSpec) -> dict[str, Any]:
        await self._pause(doc, 1.0)
        truth = self.truth_for(doc)
        if truth and (truth["doc_type"] == spec.doc_type):
            out = from_truth(truth, spec, load_quirks(self.sample_dir).get(truth["stem"], {}))
        else:
            out = heuristic_extract(doc.texts, spec)
        return add_suggestions(out) if spec.doc_type == "receipt" else out
