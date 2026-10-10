"""Confidence calibration over field-level (confidence, correct) pairs: reliability bins, ECE, Brier."""

from app.domain.models import ReliabilityBin

Pair = tuple[float, bool]


def _buckets(pairs: list[Pair], n_bins: int) -> list[list[Pair]]:
    """Equal-width bins on [0, 1]; confidence 1.0 falls in the last bin."""
    buckets: list[list[Pair]] = [[] for _ in range(n_bins)]
    for conf, ok in pairs:
        buckets[min(int(conf * n_bins), n_bins - 1)].append((conf, ok))
    return buckets


def reliability(pairs: list[Pair], n_bins: int = 10) -> list[ReliabilityBin]:
    """Reliability-diagram data; empty bins are kept with count 0."""
    return [
        ReliabilityBin(
            lo=round(i / n_bins, 4),
            hi=round((i + 1) / n_bins, 4),
            count=len(b),
            mean_confidence=round(sum(c for c, _ in b) / len(b), 4) if b else 0.0,
            accuracy=round(sum(ok for _, ok in b) / len(b), 4) if b else 0.0,
        )
        for i, b in enumerate(_buckets(pairs, n_bins))
    ]


def ece(pairs: list[Pair], n_bins: int = 10) -> float:
    """Expected calibration error: sum over bins of (bin share) * |accuracy - mean confidence|."""
    gap = sum(abs(sum(ok for _, ok in b) - sum(c for c, _ in b)) for b in _buckets(pairs, n_bins))
    return round(gap / len(pairs), 4) if pairs else 0.0


def brier(pairs: list[Pair]) -> float:
    return round(sum((conf - ok) ** 2 for conf, ok in pairs) / len(pairs), 4) if pairs else 0.0
