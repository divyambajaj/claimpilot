"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="ClaimPilot", openapi_url="/api/openapi.json")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
