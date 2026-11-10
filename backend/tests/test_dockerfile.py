"""The image must ship every sample file the app loads (a missing receipts manifest broke the live demo)."""

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_dockerfile_copies_every_sample_manifest():
    dockerfile = (BACKEND / "Dockerfile").read_text()
    copied = " ".join(line for line in dockerfile.splitlines() if line.startswith("COPY"))
    for manifest in sorted((BACKEND / "sample").glob("*.json")):
        assert f"sample/{manifest.name}" in copied, f"Dockerfile doesn't copy sample/{manifest.name}"
