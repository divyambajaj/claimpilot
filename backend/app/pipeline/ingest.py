"""Ingest: magic-byte check, PDF rasterisation, EXIF transpose, downsize, re-encode, SHA-256 and dHash."""

import contextlib
import functools
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
MAX_PDF_PAGES = 5  # shortcut: longer PDFs are truncated; raise if multi-page folios become common
ROTATIONS = (0, 90, 180, 270)


class IngestError(ValueError):
    """Upload is not a supported, readable image or PDF."""


@dataclass(frozen=True)
class Page:
    png: bytes
    width: int
    height: int
    page: int
    source_sha256: str  # hash of the uploaded bytes: the stable identity used for dedupe and replay
    dhash: str
    dhash_rotations: list[str]

    @property
    def replay_key(self) -> str:
        return f"{self.source_sha256}:{self.page}"


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise IngestError("unsupported file type (expected PNG, JPEG, WEBP or PDF)")


def dhash(img: Image.Image) -> str:
    """64-bit difference hash: 9x8 greyscale, compare horizontal neighbours."""
    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = small.tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return f"{bits:016x}"


def dhash_all_rotations(img: Image.Image) -> list[str]:
    return [dhash(img.rotate(angle, expand=True)) for angle in ROTATIONS]


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def _normalize(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return img


def _pdf_images(data: bytes) -> list[Image.Image]:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise IngestError("PDF could not be read") from exc
    try:
        return [pdf[i].render(scale=2).to_pil() for i in range(min(len(pdf), MAX_PDF_PAGES))]
    finally:
        pdf.close()


def ingest_bytes(data: bytes) -> tuple[str, list[Page]]:
    """Return (mime, pages). Every page is re-encoded as PNG, which also strips EXIF/GPS metadata."""
    mime, pages = _ingest(data)
    return mime, list(pages)


def warm_ingest(folder: Path) -> None:
    for path in sorted(folder.glob("*")) if folder.is_dir() else []:
        with contextlib.suppress(IngestError):  # not an image (e.g. manifest.json)
            _ingest(path.read_bytes())


# Pure function of the bytes: the same file (e.g. a sample receipt uploaded again) is not decoded twice.
@functools.lru_cache(maxsize=64)
def _ingest(data: bytes) -> tuple[str, tuple[Page, ...]]:
    mime = sniff_mime(data)
    source_sha = hashlib.sha256(data).hexdigest()
    if mime == "application/pdf":
        images = _pdf_images(data)
    else:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise IngestError("image could not be decoded") from exc
        images = [img]
    pages = []
    for idx, raw in enumerate(images):
        img = _normalize(raw)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=False)
        rotations = dhash_all_rotations(img)
        pages.append(Page(buf.getvalue(), img.width, img.height, idx, source_sha, rotations[0], rotations))
    return mime, tuple(pages)
