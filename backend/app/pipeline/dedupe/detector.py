"""Duplicate detector: perceptual -> fuzzy -> semantic layers, plus UPI proof-of-payment linking."""

from dataclasses import dataclass

from app.domain.enums import FindingKind, Severity
from app.domain.models import Document, Finding, LineItem
from app.pipeline.dedupe.fuzzy import FIRE_AT, amount_match, fuzzy_score
from app.pipeline.dedupe.phash import perceptual_match
from app.pipeline.dedupe.semantic import Embedder, HashedNgramEmbedder, cosine, line_text
from app.pipeline.dedupe.upi_link import is_upi_screenshot, upi_link_evidence

SEMANTIC_WITH_AMOUNT = 0.85
SEMANTIC_ALONE = 0.92


@dataclass(frozen=True)
class DuplicateMatch:
    line: LineItem
    layer: str  # perceptual | fuzzy | semantic
    score: float
    same_file: bool
    evidence: dict


@dataclass(frozen=True)
class UpiLink:
    upi_line_id: str
    invoice_line_id: str
    evidence: dict


class DuplicateDetector:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashedNgramEmbedder()

    def compare(self, new: LineItem, old: LineItem, docs: dict[str, Document]) -> DuplicateMatch | None:
        """First layer that fires decides; every layer's signal is kept as evidence."""
        layers: dict[str, dict] = {}
        fired: tuple[str, float] | None = None
        same_file = False

        perceptual = perceptual_match(
            [docs[d] for d in new.document_ids if d in docs], [docs[d] for d in old.document_ids if d in docs]
        )
        if perceptual:
            score, ev = perceptual
            layers["perceptual"] = {"score": score, **ev}
            same_file = ev["signal"] == "sha256"
            fired = ("perceptual", score)

        f_score, f_ev = fuzzy_score(new, old)
        layers["fuzzy"] = {"score": f_score, **f_ev}
        if fired is None and f_score >= FIRE_AT:
            fired = ("fuzzy", f_score)

        cos = cosine(self.embedder.embed(line_text(new)), self.embedder.embed(line_text(old)))
        amounts = amount_match(new.amount_inr, old.amount_inr)
        s_score = 0.9 if cos >= SEMANTIC_WITH_AMOUNT and amounts else 0.85 if cos >= SEMANTIC_ALONE else 0.0
        layers["semantic"] = {"score": s_score, "cosine": round(cos, 4)}
        if fired is None and s_score:
            fired = ("semantic", s_score)

        if fired is None:
            return None
        return DuplicateMatch(old, fired[0], fired[1], same_file, layers)

    def find_duplicate(
        self, new: LineItem, candidates: list[LineItem], docs: dict[str, Document]
    ) -> DuplicateMatch | None:
        """Best match among candidates of the same kind (screenshots vs screenshots, bills vs bills)."""
        best: DuplicateMatch | None = None
        for old in candidates:
            if old.id == new.id or is_upi_screenshot(old) != is_upi_screenshot(new):
                continue
            match = self.compare(new, old, docs)
            if match and (best is None or match.score > best.score):
                best = match
        return best

    @staticmethod
    def find_upi_link(new: LineItem, claim_lines: list[LineItem]) -> UpiLink | None:
        """Link a screenshot to an unlinked bill in the same claim (either upload order)."""
        for other in claim_lines:
            if other.id == new.id or other.user_excluded:
                continue
            if is_upi_screenshot(new) and not other.linked_proof_line_id:
                ev = upi_link_evidence(new, other)
                if ev:
                    return UpiLink(new.id, other.id, ev)
            elif is_upi_screenshot(other) and not other.linked_to_line_id and not new.linked_proof_line_id:
                ev = upi_link_evidence(other, new)
                if ev:
                    return UpiLink(other.id, new.id, ev)
        return None


def duplicate_finding(line: LineItem, match: DuplicateMatch) -> Finding:
    old = match.line.extracted
    what = "the same file as" if match.same_file else "a likely duplicate of"
    message = (
        f"This looks like {what} {old.vendor_name.value or 'an expense'} "
        f"₹{match.line.amount_inr:,.0f} on {old.date.value or 'an unknown date'}"
        f"{'' if match.line.claim_id == line.claim_id else ' from an earlier claim'}."
    )
    return Finding(
        id=f"{line.id}:DUPLICATE",
        kind=FindingKind.DUPLICATE,
        severity=Severity.BLOCK if match.same_file else Severity.WARN,
        rule_id="DUPLICATE",
        message=message,
        evidence={
            "matched_line_id": match.line.id,
            "matched_claim_id": match.line.claim_id,
            "matched_amount_inr": match.line.amount_inr,
            "score": match.score,
            "layer": match.layer,
            "layers": match.evidence,
        },
    )


def apply_upi_link(upi: LineItem, invoice: LineItem, link: UpiLink) -> tuple[LineItem, LineItem]:
    """The screenshot becomes proof on the bill and is excluded so it is not counted twice."""
    note = Finding(
        id=f"{upi.id}:UPI_LINK",
        kind=FindingKind.VALIDATION,
        severity=Severity.INFO,
        rule_id="UPI_LINK",
        message=f"Payment screenshot attached as proof of payment for {invoice.extracted.vendor_name.value}.",
        evidence={"linked_to": invoice.id, **link.evidence},
    )
    upi = upi.model_copy(update={"linked_to_line_id": invoice.id, "findings": [*upi.findings, note]})
    invoice = invoice.model_copy(
        update={
            "linked_proof_line_id": upi.id,
            "has_proof_of_payment": True,
            "document_ids": [
                *invoice.document_ids,
                *(d for d in upi.document_ids if d not in invoice.document_ids),
            ],
        }
    )
    return upi, invoice
