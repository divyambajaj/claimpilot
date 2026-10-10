"""SSE stream of claim progress: stage, line_update, question, claim_update, error, done."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import Container, container

router = APIRouter(tags=["events"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.get("/claims/{claim_id}/events")
async def claim_events(claim_id: str, request: Request, c: Container = Depends(container)):
    claim = c.orchestrator.get_claim(claim_id)  # 404 before opening the stream
    stream = c.broker.stream(claim_id, request.is_disconnected, first=("claim_update", {"claim": claim}))
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)
