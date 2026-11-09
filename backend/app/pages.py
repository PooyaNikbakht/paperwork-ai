"""Reading uploaded files: type sniffing, page images, the text layer, and locating quotes."""

import io
import re
import threading
from dataclasses import dataclass, field

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from app.models import Box

PREVIEW_WIDTH = 1400

# PDFium isn't thread-safe, and rendering runs in worker threads. Every PDFium call holds this.
PDFIUM_LOCK = threading.RLock()
MediaType = str

SIGNATURES: list[tuple[bytes, MediaType]] = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
]
EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}


class UnreadableFile(Exception):
    """The file isn't a PDF, PNG or JPEG we can open."""


def sniff(data: bytes) -> MediaType | None:
    """The media type from the file's first bytes, ignoring its name and declared type."""
    head = data[:1024]
    for sig, media in SIGNATURES:
        if sig == b"%PDF-":
            if sig in head:
                return media
        elif head.startswith(sig):
            return media
    return None


@dataclass
class RenderedPage:
    image: bytes  # PNG or JPEG bytes for the preview
    image_type: MediaType
    width: int
    height: int


@dataclass
class ParsedFile:
    media_type: MediaType
    pages: list[RenderedPage]
    texts: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def has_text_layer(self) -> bool:
        return any(len(t.strip()) >= 20 for t in self.texts)


def count_pages(data: bytes, media_type: MediaType) -> int:
    if media_type != "application/pdf":
        return 1
    with PDFIUM_LOCK:
        return _count_pdf_pages(data)


def _count_pdf_pages(data: bytes) -> int:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnreadableFile(
            "This PDF couldn't be opened. It may be damaged or password protected."
        ) from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def parse_file(data: bytes, media_type: MediaType, width: int = PREVIEW_WIDTH) -> ParsedFile:
    """Render preview images and read the text layer (PDFs only)."""
    if media_type == "application/pdf":
        with PDFIUM_LOCK:
            return _parse_pdf(data, width)
    return _parse_image(data, media_type, width)


def _parse_pdf(data: bytes, width: int) -> ParsedFile:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnreadableFile(
            "This PDF couldn't be opened. It may be damaged or password protected."
        ) from exc
    pages: list[RenderedPage] = []
    texts: list[str] = []
    try:
        for page in pdf:
            w, _ = page.get_size()
            bitmap = page.render(scale=width / w)
            img = bitmap.to_pil().convert("RGB")
            pages.append(_encode(img, "image/png"))
            tp = page.get_textpage()
            texts.append(tp.get_text_range())
            tp.close()
            page.close()
    finally:
        pdf.close()
    return ParsedFile("application/pdf", pages, texts)


def _parse_image(data: bytes, media_type: MediaType, width: int) -> ParsedFile:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # Pillow raises several types for bad images
        raise UnreadableFile("This image couldn't be opened.") from exc
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
    out_type = "image/png" if media_type == "image/png" else "image/jpeg"
    return ParsedFile(media_type, [_encode(img, out_type)], [""])


def _encode(img: Image.Image, media_type: MediaType) -> RenderedPage:
    buf = io.BytesIO()
    if media_type == "image/png":
        img.save(buf, "PNG", compress_level=3)
    else:
        img.save(buf, "JPEG", quality=85)
    return RenderedPage(buf.getvalue(), media_type, img.width, img.height)


def normalized_image(data: bytes) -> tuple[bytes, MediaType]:
    """An upright JPEG copy of a photo, for providers (EXIF rotation applied)."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if max(img.size) > 2400:
        img.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


# ---- Locating quotes on PDF pages ----


def _variants(quote: str) -> list[str]:
    q = " ".join(quote.split())
    out = [q]
    # Long quotes often differ from the text layer in spacing; try the first and last parts.
    if len(q) > 60:
        out.append(q[:40])
    for part in re.split(r"\s{2,}|\t|\s[|]\s", quote):
        part = " ".join(part.split())
        if len(part) >= 4 and part not in out:
            out.append(part)
    return [v for v in out if v]


class QuoteLocator:
    """Finds where a quoted string appears on a PDF page, as normalized boxes."""

    def __init__(self, data: bytes) -> None:
        PDFIUM_LOCK.acquire()
        try:
            self.pdf = pdfium.PdfDocument(data)
        except Exception:
            PDFIUM_LOCK.release()
            raise
        self._textpages: dict[int, tuple[pdfium.PdfTextPage, float, float]] = {}

    def close(self) -> None:
        try:
            for tp, _, _ in self._textpages.values():
                tp.close()
            self.pdf.close()
        finally:
            PDFIUM_LOCK.release()

    def __enter__(self) -> "QuoteLocator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _page(self, page_no: int) -> tuple[pdfium.PdfTextPage, float, float] | None:
        idx = page_no - 1
        if not 0 <= idx < len(self.pdf):
            return None
        if idx not in self._textpages:
            page = self.pdf[idx]
            w, h = page.get_size()
            self._textpages[idx] = (page.get_textpage(), w, h)
        return self._textpages[idx]

    def find(self, page_no: int, quote: str) -> list[Box] | None:
        """Boxes for the first match of `quote` on the page, or None if it isn't there."""
        entry = self._page(page_no)
        if entry is None or not quote.strip():
            return None
        tp, w, h = entry
        for variant in _variants(quote):
            searcher = tp.search(variant, match_case=False)
            hit = searcher.get_next()
            searcher.close()
            if hit is None:
                continue
            index, count = hit
            boxes = []
            for i in range(tp.count_rects(index, count)):
                left, bottom, right, top = tp.get_rect(i)
                boxes.append(
                    Box(
                        x0=round(left / w, 4),
                        y0=round((h - top) / h, 4),
                        x1=round(right / w, 4),
                        y1=round((h - bottom) / h, 4),
                    )
                )
            return _merge_lines(boxes)
        return None

    def find_any_page(self, quote: str, preferred: int) -> tuple[int, list[Box]] | None:
        """Look on the preferred page first, then the others (models sometimes miscount)."""
        order = [preferred, *[p for p in range(1, len(self.pdf) + 1) if p != preferred]]
        for p in order:
            boxes = self.find(p, quote)
            if boxes:
                return p, boxes
        return None


def _merge_lines(boxes: list[Box]) -> list[Box]:
    """Merge boxes on the same line into one, so a quote highlights as one bar per line."""
    lines: list[Box] = []
    for b in sorted(boxes, key=lambda b: (round(b.y0, 2), b.x0)):
        last = lines[-1] if lines else None
        if last and abs(last.y0 - b.y0) < 0.006 and abs(last.y1 - b.y1) < 0.006:
            lines[-1] = Box(
                x0=min(last.x0, b.x0),
                y0=min(last.y0, b.y0),
                x1=max(last.x1, b.x1),
                y1=max(last.y1, b.y1),
            )
        else:
            lines.append(b)
    return lines
