"""Demo gallery of pre-recorded synthetic receipts (the primary path on the keyless hosted demo)."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import Container, container
from app.api.schemas import DemoReceipt

router = APIRouter(tags=["demo"])
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".pdf")


def demo_path(demo_dir: Path, name: str) -> Path:
    stem = Path(name).stem
    for suffix in IMAGE_SUFFIXES:
        path = demo_dir / f"{stem}{suffix}"
        if path.is_file() and path.parent == demo_dir:
            return path
    raise HTTPException(404, f"{name} is not in the demo gallery")


@router.get("/demo/receipts", response_model=list[DemoReceipt])
def receipts(c: Container = Depends(container)):
    manifest_path = c.settings.demo_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    return [
        DemoReceipt(name=Path(file).stem, thumbnail_url=f"/api/demo/receipts/{Path(file).stem}/image", **meta)
        for file, meta in manifest.items()
    ]


@router.get("/demo/receipts/{name}/image")
def receipt_image(name: str, c: Container = Depends(container)):
    return FileResponse(demo_path(c.settings.demo_dir, name))
