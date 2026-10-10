"""Claim orchestrator: runs the pipeline in the background, owns state changes, emits SSE events and spans."""

import asyncio
import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.api.sse import Broker
from app.config import Settings
from app.domain.enums import Category, ClaimStatus, FindingKind, LineStatus
from app.domain.models import (
    EXTRACTED_FIELD_NAMES,
    Claim,
    CorrectionLabel,
    Document,
    ExtractedReceipt,
    FieldEdit,
    LineItem,
    SubmissionLine,
    SubmissionPayload,
)
from app.domain.repo import Repo
from app.domain.state import derive_claim_status, derive_line_status, ensure_editable, ensure_submittable
from app.finance_mock import MockFinance
from app.llm.base import ImageInput, LLMError, ReplayMissError
from app.llm.client import LLMClient
from app.observability.tracing import Tracer, new_id, utcnow
from app.pipeline.dedupe.detector import DuplicateDetector, apply_upi_link, duplicate_finding
from app.pipeline.extract import amount_in_inr, normalize_field, parse_extraction
from app.pipeline.ingest import Page, ingest_bytes
from app.pipeline.planner import DUPLICATE_CHOICES, PlanContext, plan, sticky
from app.pipeline.validate.confidence import adjust_confidence, validation_findings
from app.rules.dsl import RuleSet
from app.rules.engine import evaluate, merge_resolutions

DUPLICATE_ANSWERS = {
    "confirm": "confirmed",
    "override": "overridden",
    DUPLICATE_CHOICES[0].lower(): "confirmed",
    DUPLICATE_CHOICES[1].lower(): "overridden",
}


class AnswerError(ValueError):
    """An answer or edit could not be applied (mapped to HTTP 422)."""


@dataclass(frozen=True)
class Upload:
    filename: str
    data: bytes


@dataclass(frozen=True)
class _Unit:
    filename: str
    docs: list[Document]
    images: list[ImageInput]


def reassess(claim: Claim, ctx: PlanContext) -> Claim:
    """Validate -> rules -> plan -> statuses. Pure: no I/O, no LLM. Run after every change."""
    lines = [line.model_copy(deep=True) for line in claim.lines]
    result = evaluate(lines, ctx.ruleset, ctx.today, ctx.prior_day_totals)
    for line in lines:
        out = result.lines.get(line.id)
        if out is None:  # excluded/linked/error lines keep their findings (and resolutions) untouched
            continue
        fresh = validation_findings(line.extracted, line.id, ctx.today) + out.findings
        line.findings = sticky(line.findings) + merge_resolutions(line.findings, fresh)
        line.category = out.category
    claim = claim.model_copy(
        update={"lines": lines, "findings": merge_resolutions(claim.findings, result.claim_findings)}
    )
    p = plan(claim, ctx)
    for line in lines:
        line.assumed_fields = p.assumed.get(line.id, [])
        for name in line.assumed_fields:
            f = line.extracted.field(name)
            if f.origin == "llm":
                f.origin = "assumed"
        line.status = derive_line_status(line, p.all)
        out = result.lines.get(line.id)
        excluded = line.status in (LineStatus.EXCLUDED, LineStatus.ERROR) or out is None
        line.reimbursable_inr = 0.0 if excluded else out.reimbursable_inr  # type: ignore[union-attr]
    claim.open_questions = p.asked
    claim.total_inr = round(sum(x.amount_inr for x in lines if not (x.linked_to_line_id or x.error)), 2)
    claim.reimbursable_inr = round(sum(x.reimbursable_inr for x in lines), 2)
    claim.status = derive_claim_status(claim)
    return claim


def count_asked(claim: Claim, shown_before: set[str]) -> Claim:
    """Count questions the user is now seeing for the first time (questions-per-claim metric)."""
    new = [q for q in claim.open_questions if q.id not in shown_before]
    lines = [
        x.model_copy(update={"questions_asked": x.questions_asked + sum(q.line_id == x.id for q in new)})
        for x in claim.lines
    ]
    return claim.model_copy(update={"lines": lines, "questions_asked": claim.questions_asked + len(new)})


def set_field(
    line: LineItem, name: str, raw: Any, now: dt.datetime
) -> tuple[LineItem, CorrectionLabel | None]:
    """Apply a user-provided value (origin=user, confidence 1.0) and keep amount/category in sync."""
    if name not in EXTRACTED_FIELD_NAMES:
        raise AnswerError(f"unknown field {name}")
    normalized = normalize_field(name, {"value": raw, "confidence": 1.0})
    value = normalized["value"]
    if (raw not in (None, "") and value is None) or normalized["confidence"] < 1.0:
        raise AnswerError(f"{raw!r} is not a valid {name.replace('_', ' ')}")
    line = line.model_copy(deep=True)
    f = line.extracted.field(name)
    old, old_conf = f.value, f.confidence
    new = type(f).model_validate({**f.model_dump(), "value": value}).value
    f.history.append(FieldEdit(at=now, old_value=_plain(old), new_value=_plain(new)))
    f.value, f.confidence, f.origin = new, 1.0, "user"
    if name in ("total_amount", "currency"):
        line.amount_inr = amount_in_inr(line.extracted)
    if name == "category" and new is not None:
        line.category = Category(new)
    label = None
    if old != new:
        label = CorrectionLabel(
            id=new_id("lbl"),
            line_id=line.id,
            field=name,
            predicted=_plain(old),
            confidence=old_conf,
            corrected=_plain(new),
            created_at=now,
        )
    return line, label


def _plain(value: Any) -> Any:
    if isinstance(value, dt.date):
        return value.isoformat()
    return getattr(value, "value", value)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        llm: LLMClient,
        tracer: Tracer,
        broker: Broker,
        finance: MockFinance,
        clock: Callable[[], dt.datetime] = utcnow,
        detector: DuplicateDetector | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.llm = llm
        self.tracer = tracer
        self.broker = broker
        self.finance = finance
        self.clock = clock
        self.detector = detector or DuplicateDetector()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task[None]] = set()

    # --- helpers --------------------------------------------------------------------------------------
    def ruleset(self) -> RuleSet:
        ruleset = self.repo.active_ruleset()
        if ruleset is None:
            raise RuntimeError("no active ruleset; load data/rulesets/acme_v1.json")
        return ruleset

    def context(self, claim: Claim) -> PlanContext:
        return PlanContext(
            ruleset=self.ruleset(),
            today=self.clock().date(),
            prior_day_totals=self.repo.prior_day_category_totals(claim.user_id, claim.id),
            tau=self.settings.TAU,
            max_questions=self.settings.MAX_QUESTIONS_PER_ROUND,
        )

    def _save(self, claim: Claim) -> Claim:
        claim = claim.model_copy(update={"updated_at": self.clock()})
        self.repo.save_claim(claim)
        return claim

    def _publish(self, claim_id: str, event: str, data: Any) -> None:
        self.broker.publish(claim_id, event, data)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # --- claims ---------------------------------------------------------------------------------------
    def create_claim(self, user_id: str, title: str | None) -> Claim:
        now = self.clock()
        claim = Claim(
            id=new_id("clm"),
            user_id=user_id,
            title=title or f"Expenses {now:%d %b %Y}",
            status=ClaimStatus.DRAFT,
            ruleset_version=self.ruleset().version,
            created_at=now,
            updated_at=now,
        )
        self.repo.save_claim(claim)
        return claim

    def get_claim(self, claim_id: str) -> Claim:
        claim = self.repo.get_claim(claim_id)
        if claim.status == ClaimStatus.SUBMITTED and claim.finance_reference:
            sub = self.finance.poll(claim.finance_reference, self.clock())
            if sub.status != "submitted":
                claim = self._save(claim.model_copy(update={"status": ClaimStatus(sub.status)}))
        return claim

    # --- documents ------------------------------------------------------------------------------------
    async def add_documents(self, claim_id: str, uploads: list[Upload]) -> list[str]:
        """Ingest synchronously (bad files fail the request), then extract in the background."""
        claim = self.repo.get_claim(claim_id)
        ensure_editable(claim)
        trace_id = self.tracer.start_trace("claim", claim_id)
        units: list[_Unit] = []
        with self.tracer.use_trace(trace_id):
            for up in uploads:
                with self.tracer.span("ingest", filename=up.filename, bytes=len(up.data)) as span:
                    mime, pages = await asyncio.to_thread(ingest_bytes, up.data)
                    span.set(mime=mime, pages=len(pages))
                units.append(self._unit(claim_id, up.filename, mime, pages))
        for unit in units:
            if not self.llm.can_serve(unit.images):
                raise ReplayMissError(unit.docs[0].sha256)
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        for unit in units:
            for doc, img in zip(unit.docs, unit.images, strict=True):
                await asyncio.to_thread(_write, doc.stored_path, img.data)
                self.repo.save_document(doc)
            self._publish(
                claim_id, "stage", {"doc_id": unit.docs[0].id, "filename": unit.filename, "stage": "ingest"}
            )
        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            claim.processing += len(units)
            claim.status = derive_claim_status(claim)
            self._save(claim)
        shown = {q.id for q in claim.open_questions}
        task = asyncio.create_task(self._process(claim_id, units, trace_id, shown))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return [d.id for u in units for d in u.docs]

    def _unit(self, claim_id: str, filename: str, mime: str, pages: list[Page]) -> _Unit:
        docs, images = [], []
        for page in pages:
            doc_id = new_id("doc")
            path = str((self.settings.uploads_dir / f"{doc_id}.png").resolve())
            docs.append(
                Document(
                    id=doc_id,
                    claim_id=claim_id,
                    filename=filename,
                    mime=mime,
                    sha256=page.source_sha256,
                    dhash=page.dhash,
                    dhash_rotations=page.dhash_rotations,
                    width=page.width,
                    height=page.height,
                    page=page.page,
                    stored_path=path,
                )
            )
            images.append(ImageInput(data=page.png, key=page.replay_key, path=path))
        return _Unit(filename, docs, images)

    async def _process(self, claim_id: str, units: list[_Unit], trace_id: str, shown: set[str]) -> None:
        with self.tracer.use_trace(trace_id):
            await asyncio.gather(*(self._process_unit(claim_id, u) for u in units))
        async with self._locks[claim_id]:
            claim = self._save(count_asked(self.repo.get_claim(claim_id), shown))
        self._publish(claim_id, "question", {"questions": claim.open_questions})
        self._publish(claim_id, "done", {"claim": claim})

    async def _process_unit(self, claim_id: str, unit: _Unit) -> None:
        doc_id, today = unit.docs[0].id, self.clock().date()

        def stage(name: str, message: str | None = None) -> None:
            payload = {"doc_id": doc_id, "filename": unit.filename, "stage": name}
            self._publish(claim_id, "stage", payload | ({"message": message} if message else {}))

        stage("extract")
        error = None
        try:
            with self.tracer.span("extract", doc_id=doc_id, filename=unit.filename) as span:
                receipt, resp = await self.llm.extract(unit.images)
                span.set(
                    provider=resp.provider, model=resp.model, replayed=resp.replayed, attempt=resp.attempt
                )
        except LLMError as exc:
            receipt, error = parse_extraction({"raw_text": ""}), f"Could not read this document: {exc}"
            self._publish(claim_id, "error", {"message": error, "doc_id": doc_id, "code": type(exc).__name__})
        stage("validate")
        with self.tracer.span("validate", doc_id=doc_id):
            receipt = adjust_confidence(receipt, today)
        line = self._new_line(claim_id, unit, receipt, error)

        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            stage("dedupe")
            with self.tracer.span("dedupe", doc_id=doc_id) as span:
                claim = self._dedupe(claim, line)
                span.set(findings=[f.rule_id for f in claim.lines[-1].findings])
            stage("rules")
            claim.processing = max(0, claim.processing - 1)
            with self.tracer.span("rules", doc_id=doc_id), self.tracer.span("plan") as span:
                claim = reassess(claim, self.context(claim))
                span.set(questions=len(claim.open_questions))
            claim = self._save(claim)
        self._publish(claim_id, "line_update", {"line": next(x for x in claim.lines if x.id == line.id)})
        self._publish(claim_id, "claim_update", {"claim": claim})
        stage("error" if error else "done", error)

    def _new_line(self, claim_id: str, unit: _Unit, receipt: ExtractedReceipt, error: str | None) -> LineItem:
        amount = amount_in_inr(receipt)
        date, city = receipt.date.value, receipt.city.value
        return LineItem(
            id=new_id("ln"),
            claim_id=claim_id,
            document_ids=[d.id for d in unit.docs],
            extracted=receipt,
            category=receipt.category.value or Category.OTHER,
            amount_inr=amount,
            reimbursable_inr=amount,
            status=LineStatus.ERROR if error else LineStatus.PROCESSING,
            error=error,
            trip_key=f"{date}:{city}" if date and city else None,
            created_at=self.clock(),
        )

    def _dedupe(self, claim: Claim, line: LineItem) -> Claim:
        """Append `line` to the claim after UPI linking / duplicate checks against the user's history."""
        lines = [*claim.lines, line]
        if line.error:
            return claim.model_copy(update={"lines": lines})
        link = self.detector.find_upi_link(line, claim.lines)
        if link:
            by_id = {x.id: x for x in lines}
            upi, invoice = apply_upi_link(by_id[link.upi_line_id], by_id[link.invoice_line_id], link)
            lines = [upi if x.id == upi.id else invoice if x.id == invoice.id else x for x in lines]
            return claim.model_copy(update={"lines": lines})
        history = self.repo.user_lines_near(
            claim.user_id, line.extracted.date.value, self.settings.DEDUPE_WINDOW_DAYS, claim.id
        )
        candidates = [*history, *(x for x in claim.lines if not x.user_excluded)]
        docs = self.repo.get_documents([d for x in [line, *candidates] for d in x.document_ids])
        match = self.detector.find_duplicate(line, candidates, docs)
        if match:
            line = line.model_copy(update={"findings": [*line.findings, duplicate_finding(line, match)]})
            lines[-1] = line
        return claim.model_copy(update={"lines": lines})

    # --- answers, edits, actions ----------------------------------------------------------------------
    async def answer(self, claim_id: str, answers: list[dict[str, Any]]) -> Claim:
        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            ensure_editable(claim)
            questions = {q.id: q for q in claim.open_questions}
            for a in answers:
                q = questions.get(a.get("question_id") or "")
                if q is None and a.get("question_id"):
                    raise AnswerError(f"question {a['question_id']} is not open")
                line_id = q.line_id if q else a.get("line_id")
                name = q.field if q else a.get("field")
                if not line_id or not name:
                    raise AnswerError("each answer needs question_id, or line_id and field")
                if q is None or q.kind in ("value", "choice"):
                    claim = self._edit_field(claim, line_id, name, a.get("value"))
                elif q.kind == "confirm_duplicate":
                    resolution = DUPLICATE_ANSWERS.get(str(a.get("value")).lower())
                    if resolution is None:
                        raise AnswerError("answer a duplicate question with 'confirm' or 'override'")
                    claim = _resolve(claim, line_id, lambda f, fid=q.finding_id: f.id == fid, resolution)
                else:
                    text = str(a.get("value") or "").strip()
                    if not text:
                        raise AnswerError("a justification needs some text")
                    claim = _resolve(
                        claim, line_id, lambda f, fid=q.finding_id: f.id == fid, "justified", text
                    )
            claim.answers_received += len(answers)
            return self._commit(claim)

    async def edit_line(self, claim_id: str, line_id: str, patch: dict[str, Any]) -> Claim:
        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            ensure_editable(claim)
            for name, value in patch.items():
                claim = self._edit_field(claim, line_id, name, value)
            return self._commit(claim)

    async def line_action(self, claim_id: str, line_id: str, action: str, justification: str | None) -> Claim:
        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            ensure_editable(claim)
            line = _line(claim, line_id)
            is_dup = lambda f: f.kind == FindingKind.DUPLICATE  # noqa: E731
            match action:
                case "exclude" | "restore":
                    claim = _replace(claim, line.model_copy(update={"user_excluded": action == "exclude"}))
                case "override_duplicate":
                    claim = _resolve(claim, line_id, is_dup, "overridden")
                case "confirm_duplicate":
                    claim = _resolve(claim, line_id, is_dup, "confirmed")
                case "justify":
                    if not (justification or "").strip():
                        raise AnswerError("a justification needs some text")
                    claim = _resolve(
                        claim, line_id, lambda f: f.kind == FindingKind.POLICY, "justified", justification
                    )
                case _:
                    raise AnswerError(f"unknown action {action}")
            return self._commit(claim)

    def _edit_field(self, claim: Claim, line_id: str, name: str, value: Any) -> Claim:
        line, label = set_field(_line(claim, line_id), name, value, self.clock())
        if label:
            self.repo.add_label(label)
        return _replace(claim, line)

    def _commit(self, claim: Claim) -> Claim:
        shown = {q.id for q in claim.open_questions}
        with self.tracer.trace("claim", claim.id), self.tracer.span("rules"), self.tracer.span("plan"):
            claim = reassess(claim, self.context(claim))
        claim = self._save(count_asked(claim, shown))
        self._publish(claim.id, "claim_update", {"claim": claim})
        self._publish(claim.id, "question", {"questions": claim.open_questions})
        return claim

    # --- submit ---------------------------------------------------------------------------------------
    async def submit(self, claim_id: str) -> Claim:
        async with self._locks[claim_id]:
            claim = self.repo.get_claim(claim_id)
            ensure_submittable(claim)
            with self.tracer.trace("claim", claim_id), self.tracer.span("submit") as span:
                payload = SubmissionPayload(
                    claim_id=claim.id,
                    user_id=claim.user_id,
                    title=claim.title,
                    ruleset_version=claim.ruleset_version,
                    lines=[_submission_line(x) for x in claim.lines if x.status == LineStatus.COMPLETE],
                    total_reimbursable_inr=claim.reimbursable_inr,
                )
                now = self.clock()
                sub = self.finance.submit(payload, now)
                span.set(reference=sub.reference, amount_inr=payload.total_reimbursable_inr)
            claim = claim.model_copy(
                update={
                    "status": ClaimStatus.SUBMITTED,
                    "finance_reference": sub.reference,
                    "submitted_at": now,
                }
            )
            claim = self._save(claim)
            self._publish(claim_id, "claim_update", {"claim": claim})
            return claim


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def _line(claim: Claim, line_id: str) -> LineItem:
    for line in claim.lines:
        if line.id == line_id:
            return line
    raise AnswerError(f"line {line_id} is not part of claim {claim.id}")


def _replace(claim: Claim, line: LineItem) -> Claim:
    return claim.model_copy(update={"lines": [line if x.id == line.id else x for x in claim.lines]})


def _resolve(
    claim: Claim,
    line_id: str,
    which: Callable[[Any], bool],
    resolution: str,
    justification: str | None = None,
) -> Claim:
    line = _line(claim, line_id)
    findings = [
        f.model_copy(update={"resolution": resolution, "justification": justification})
        if which(f) and f.resolution == "open"
        else f
        for f in line.findings
    ]
    return _replace(claim, line.model_copy(update={"findings": findings}))


def _submission_line(line: LineItem) -> SubmissionLine:
    r = line.extracted
    notes = [f.justification for f in line.findings if f.justification]
    return SubmissionLine(
        line_id=line.id,
        date=r.date.value,
        category=line.category,
        vendor_name=r.vendor_name.value,
        vendor_gstin=r.vendor_gstin.value,
        invoice_number=r.invoice_number.value,
        amount_inr=line.amount_inr,
        reimbursable_inr=line.reimbursable_inr,
        justification="; ".join(notes) or None,
    )
