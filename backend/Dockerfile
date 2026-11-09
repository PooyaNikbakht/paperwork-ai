# Small production image for Google Cloud Run (also works on Render, Fly or Railway).
FROM python:3.12-slim

# uv from PyPI rather than ghcr.io, so the image also builds on IPv6-only hosts.
RUN pip install --no-cache-dir "uv==0.13.*"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8080 \
    DATA_DIR=/tmp/paperwork-data

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY sample/documents ./sample/documents
COPY sample/truth ./sample/truth
COPY sample/manifest.json sample/demo_quirks.json ./sample/

RUN useradd --create-home appuser
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "/app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
