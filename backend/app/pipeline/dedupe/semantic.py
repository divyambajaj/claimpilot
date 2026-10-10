"""Layer 3: lightweight lexical embedding (hashed char 3-5-grams) for re-photographed or re-printed bills."""

import zlib
from typing import Protocol

import numpy as np

from app.domain.models import LineItem

DIMS = 4096


class Embedder(Protocol):
    def embed(self, text: str) -> np.ndarray: ...


class HashedNgramEmbedder:
    """Deterministic and offline: crc32-hashed char n-gram counts, L2-normalised."""

    def __init__(self, dims: int = DIMS, n_min: int = 3, n_max: int = 5) -> None:
        self.dims, self.n_min, self.n_max = dims, n_min, n_max

    def embed(self, text: str) -> np.ndarray:
        norm = " ".join(text.lower().split())
        vec = np.zeros(self.dims, dtype=np.float32)
        for n in range(self.n_min, self.n_max + 1):
            for i in range(len(norm) - n + 1):
                vec[zlib.crc32(norm[i : i + n].encode()) % self.dims] += 1.0
        length = float(np.linalg.norm(vec))
        return vec / length if length else vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # inputs are unit-length


def line_text(line: LineItem) -> str:
    items = " ".join(i.description for i in line.extracted.items)
    return f"{line.extracted.raw_text} {items}".strip()
