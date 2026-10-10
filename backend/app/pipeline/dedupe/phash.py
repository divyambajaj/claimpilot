"""Layer 1: identical file (SHA-256) or near-identical image (dHash Hamming distance, rotation-invariant)."""

from app.domain.models import Document
from app.pipeline.ingest import hamming

HAMMING_MAX = 6


def perceptual_match(new_docs: list[Document], old_docs: list[Document]) -> tuple[float, dict] | None:
    """Return (score, evidence) for the closest page pair, or None if nothing is close."""
    best: tuple[float, dict] | None = None
    for a in new_docs:
        for b in old_docs:
            if a.sha256 == b.sha256:
                return 1.0, {"signal": "sha256", "hamming": 0}
            distance = min(hamming(rot, b.dhash) for rot in a.dhash_rotations or [a.dhash])
            if distance <= HAMMING_MAX and (best is None or distance < best[1]["hamming"]):
                best = (0.97, {"signal": "dhash", "hamming": distance})
    return best
