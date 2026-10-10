"""Provider-neutral LLM request/response types and errors (section 9)."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.llm.fingerprint import fingerprint, sha256_hex


class ImageInput(BaseModel):
    data: bytes
    mime: str = "image/png"
    path: str | None = None  # absolute local path, needed by the claude_code CLI provider
    # Stable identity for replay (upload sha + page); re-encoded PNG bytes can differ across zlib builds.
    key: str | None = None

    def identity(self) -> str:
        return self.key or sha256_hex(self.data)


class LLMRequest(BaseModel):
    prompt_name: str
    prompt_version: str
    system: str
    user_text: str
    images: list[ImageInput] = Field(default_factory=list)
    json_schema: dict[str, Any]  # named json_schema: `schema` shadows a BaseModel attribute
    max_tokens: int = 4096
    temperature: float = 0.0

    def fingerprint(self) -> str:
        return fingerprint(
            self.prompt_name,
            self.prompt_version,
            self.json_schema,
            self.system + "\n" + self.user_text,
            [img.identity() for img in self.images],
        )


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMResponse(BaseModel):
    data: dict[str, Any]
    raw_text: str
    provider: str
    model: str
    latency_ms: int
    usage: Usage = Field(default_factory=Usage)
    replayed: bool = False
    attempt: int = 1


class LLMProvider(Protocol):
    name: str
    model: str
    supports_vision: bool

    async def complete_structured(self, req: LLMRequest) -> LLMResponse: ...


class LLMError(Exception):
    """Non-retryable provider failure."""


class TransportError(LLMError):
    """Retryable failure (network, timeout, 429, 5xx)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MalformedOutputError(LLMError):
    """The provider answered but the payload is not parseable JSON; eligible for a repair retry."""

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class ReplayMissError(LLMError):
    """No recorded response exists for this request fingerprint."""

    def __init__(self, fp: str) -> None:
        super().__init__(f"no recorded response for fingerprint {fp}")
        self.fingerprint = fp
