import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import SourceFile
from app.settings import SAMPLE_DIR, Settings

DOCS = SAMPLE_DIR / "documents"


def sample_bytes(name: str) -> bytes:
    return (DOCS / name).read_bytes()


def sample_source(name: str) -> SourceFile:
    data = sample_bytes(name)
    media = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg"}[
        name.rsplit(".", 1)[1]
    ]
    return SourceFile(data, media, name, hashlib.sha256(data).hexdigest())


def truth(stem: str) -> dict:
    return json.loads((SAMPLE_DIR / "truth" / f"{stem}.json").read_text())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        llm_provider="mock",
        mock_delay_seconds=0,
        anthropic_api_key="",
        openai_api_key="",
    )


def make_client(settings: Settings, provider=None) -> TestClient:
    return TestClient(create_app(settings, provider))


@pytest.fixture
def client(settings: Settings):
    with make_client(settings) as c:
        yield c


def wait_for_batch(client: TestClient, batch_id: str, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    while True:
        batch = client.get(f"/batches/{batch_id}").json()
        if all(d["status"] not in ("queued", "extracting") for d in batch["documents"]):
            return batch
        if time.time() > deadline:
            raise AssertionError(f"batch still running: {batch}")
        time.sleep(0.05)


def by_file(batch: dict) -> dict[str, dict]:
    return {d["filename"]: d for d in batch["documents"]}
