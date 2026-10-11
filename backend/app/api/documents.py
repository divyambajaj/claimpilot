"""Document upload (multipart or demo gallery) -> 202 + background processing."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.demo import demo_path
from app.api.deps import Container, container
from app.api.schemas import DemoSelection, DocumentIds
from app.pipeline.orchestrator import Upload

router = APIRouter(tags=["documents"])


@router.post("/claims/{claim_id}/documents", status_code=202, response_model=DocumentIds)
async def upload(
    claim_id: str, files: list[UploadFile], for_line_id: str | None = None, c: Container = Depends(container)
):
    """`for_line_id`: one bill for that payment screenshot, read now; 422 (nothing stored) if it is not it."""
    s = c.settings
    if not files or len(files) > (1 if for_line_id else s.MAX_FILES_PER_REQUEST):
        raise HTTPException(400, f"send between 1 and {1 if for_line_id else s.MAX_FILES_PER_REQUEST} files")
    uploads = []
    for f in files:
        data = await f.read(s.MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > s.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} is larger than {s.MAX_UPLOAD_MB} MB")
        uploads.append(Upload(f.filename or "upload", data))
    if for_line_id:
        ids = await c.orchestrator.attach_document(claim_id, for_line_id, uploads[0])
        return DocumentIds(document_ids=ids)
    return DocumentIds(document_ids=await c.orchestrator.add_documents(claim_id, uploads))


@router.post("/claims/{claim_id}/documents/from-demo", status_code=202, response_model=DocumentIds)
async def from_demo(claim_id: str, body: DemoSelection, c: Container = Depends(container)):
    if not body.names:
        raise HTTPException(400, "choose at least one sample receipt")
    uploads = []
    for name in body.names:
        path = demo_path(c.settings.demo_dir, name)
        uploads.append(Upload(path.name, path.read_bytes()))
    return DocumentIds(document_ids=await c.orchestrator.add_documents(claim_id, uploads))
