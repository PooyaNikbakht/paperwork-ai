"""SQLite for batches and documents, plus files on disk. Small, synchronous, and fast enough.

Writes go through one lock; reads open short-lived cursors on the same connection.
"""

import json
import secrets
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import BatchMode, Check, DocStatus, DocType, Extraction, FieldSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    mode TEXT NOT NULL,
    custom_fields TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0,
    client_ip TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    page_sizes TEXT NOT NULL DEFAULT '[]',
    page_texts TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    doc_type TEXT,
    extraction TEXT,
    checks TEXT NOT NULL DEFAULT '[]',
    provider TEXT,
    model TEXT,
    demo_reason TEXT,
    error TEXT,
    dup_key TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    approved_at REAL
);
CREATE INDEX IF NOT EXISTS documents_batch ON documents(batch_id, position);
CREATE INDEX IF NOT EXISTS documents_dup ON documents(dup_key);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


@dataclass
class Batch:
    id: str
    created_at: float
    mode: BatchMode
    custom_fields: list[FieldSpec] | None
    is_sample: bool
    client_ip: str


@dataclass
class Document:
    id: str
    batch_id: str
    position: int
    filename: str
    media_type: str
    size: int
    sha256: str
    status: DocStatus
    created_at: float
    updated_at: float
    page_count: int = 0
    page_sizes: list[list[int]] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)
    doc_type: DocType | None = None
    extraction: Extraction | None = None
    checks: list[Check] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    demo_reason: str | None = None
    error: str | None = None
    dup_key: str | None = None
    approved_at: float | None = None

    @property
    def has_text_layer(self) -> bool:
        return any(len(t.strip()) >= 20 for t in self.page_texts)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "files").mkdir(exist_ok=True)
        self._db = sqlite3.connect(data_dir / "paperwork.db", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._db.close()

    # ---- batches ----

    def create_batch(
        self,
        mode: BatchMode,
        custom_fields: list[FieldSpec] | None = None,
        *,
        is_sample: bool = False,
        client_ip: str = "",
    ) -> Batch:
        batch = Batch(new_id("bat"), time.time(), mode, custom_fields, is_sample, client_ip)
        fields_json = json.dumps([f.model_dump() for f in custom_fields]) if custom_fields else None
        with self._lock:
            self._db.execute(
                "INSERT INTO batches VALUES (?, ?, ?, ?, ?, ?)",
                (batch.id, batch.created_at, mode, fields_json, int(is_sample), client_ip),
            )
            self._db.commit()
        return batch

    def get_batch(self, batch_id: str) -> Batch | None:
        row = self._db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            return None
        fields = row["custom_fields"]
        return Batch(
            id=row["id"],
            created_at=row["created_at"],
            mode=row["mode"],
            custom_fields=[FieldSpec(**f) for f in json.loads(fields)] if fields else None,
            is_sample=bool(row["is_sample"]),
            client_ip=row["client_ip"],
        )

    def delete_batch(self, batch_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
            self._db.commit()
        shutil.rmtree(self.batch_dir(batch_id), ignore_errors=True)

    def expired_batches(self, older_than: float) -> list[str]:
        rows = self._db.execute(
            "SELECT id FROM batches WHERE created_at < ?", (older_than,)
        ).fetchall()
        return [r["id"] for r in rows]

    # ---- documents ----

    def add_document(
        self, batch_id: str, filename: str, media_type: str, data: bytes, sha256: str
    ) -> Document:
        now = time.time()
        with self._lock:
            pos = self._db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM documents WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()[0]
            doc = Document(
                id=new_id("doc"),
                batch_id=batch_id,
                position=pos,
                filename=filename,
                media_type=media_type,
                size=len(data),
                sha256=sha256,
                status="queued",
                created_at=now,
                updated_at=now,
            )
            path = self.original_path(doc)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self._db.execute(
                """INSERT INTO documents (id, batch_id, position, filename, media_type, size,
                   sha256, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc.id,
                    batch_id,
                    pos,
                    filename,
                    media_type,
                    len(data),
                    sha256,
                    "queued",
                    now,
                    now,
                ),
            )
            self._db.commit()
        return doc

    def get_document(self, doc_id: str) -> Document | None:
        row = self._db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return _doc(row) if row else None

    def list_documents(self, batch_id: str) -> list[Document]:
        rows = self._db.execute(
            "SELECT * FROM documents WHERE batch_id = ? ORDER BY position", (batch_id,)
        ).fetchall()
        return [_doc(r) for r in rows]

    def documents_with_status(self, *statuses: str) -> list[Document]:
        marks = ",".join("?" * len(statuses))
        rows = self._db.execute(
            f"SELECT * FROM documents WHERE status IN ({marks}) ORDER BY created_at", statuses
        ).fetchall()
        return [_doc(r) for r in rows]

    def find_by_dup_key(self, dup_key: str) -> list[Document]:
        rows = self._db.execute(
            "SELECT * FROM documents WHERE dup_key = ? ORDER BY created_at, position", (dup_key,)
        ).fetchall()
        return [_doc(r) for r in rows]

    def update_document(self, doc_id: str, **changes: Any) -> None:
        if not changes:
            return
        cols = []
        values: list[Any] = []
        for key, value in changes.items():
            cols.append(f"{key} = ?")
            values.append(_encode(key, value))
        cols.append("updated_at = ?")
        values.append(time.time())
        with self._lock:
            self._db.execute(
                f"UPDATE documents SET {', '.join(cols)} WHERE id = ?", (*values, doc_id)
            )
            self._db.commit()

    # ---- files ----

    def batch_dir(self, batch_id: str) -> Path:
        return self.data_dir / "files" / batch_id

    def doc_dir(self, doc: Document) -> Path:
        return self.batch_dir(doc.batch_id) / doc.id

    def original_path(self, doc: Document) -> Path:
        ext = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[doc.media_type]
        return self.doc_dir(doc) / f"original.{ext}"

    def page_path(self, doc: Document, page: int) -> Path | None:
        for ext in ("png", "jpg"):
            p = self.doc_dir(doc) / f"page-{page}.{ext}"
            if p.exists():
                return p
        return None

    def read_original(self, doc: Document) -> bytes:
        return self.original_path(doc).read_bytes()


_JSON_COLUMNS = {"page_sizes", "page_texts", "extraction", "checks"}


def _encode(key: str, value: Any) -> Any:
    if key == "extraction":
        return value.model_dump_json() if value is not None else None
    if key == "checks":
        return json.dumps([c.model_dump() for c in value])
    if key in _JSON_COLUMNS:
        return json.dumps(value)
    return value


def _doc(row: sqlite3.Row) -> Document:
    extraction = row["extraction"]
    return Document(
        id=row["id"],
        batch_id=row["batch_id"],
        position=row["position"],
        filename=row["filename"],
        media_type=row["media_type"],
        size=row["size"],
        sha256=row["sha256"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        page_count=row["page_count"],
        page_sizes=json.loads(row["page_sizes"]),
        page_texts=json.loads(row["page_texts"]),
        doc_type=row["doc_type"],
        extraction=Extraction.model_validate_json(extraction) if extraction else None,
        checks=[Check(**c) for c in json.loads(row["checks"])],
        provider=row["provider"],
        model=row["model"],
        demo_reason=row["demo_reason"],
        error=row["error"],
        dup_key=row["dup_key"],
        approved_at=row["approved_at"],
    )
