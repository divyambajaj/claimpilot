"""Minimal OpenTelemetry-style tracer: nested spans via contextvars, persisted to SQLite."""

import datetime as dt
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select

from app.db import Database, SpanRow, TraceRow
from app.domain.models import Span, Trace

SpanStatus = Literal["ok", "error", "retry"]
TraceKind = Literal["claim", "policy", "eval"]

_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class SpanHandle:
    id: str
    trace_id: str
    parent_id: str | None
    name: str
    start: dt.datetime
    attributes: dict[str, Any] = field(default_factory=dict)
    status: SpanStatus = "ok"

    def set(self, **attrs: Any) -> None:
        self.attributes.update(attrs)


class Tracer:
    def __init__(self, db: Database | None) -> None:
        self.db = db

    def start_trace(self, kind: TraceKind, claim_id: str | None = None) -> str:
        trace_id = new_id("tr")
        if self.db is not None:
            with self.db.session() as s:
                s.add(TraceRow(id=trace_id, claim_id=claim_id, kind=kind, created_at=utcnow()))
        return trace_id

    @contextmanager
    def trace(self, kind: TraceKind, claim_id: str | None = None) -> Iterator[str]:
        """Start a trace and make it current for nested spans."""
        trace_id = self.start_trace(kind, claim_id)
        token = _current_trace.set(trace_id)
        try:
            yield trace_id
        finally:
            _current_trace.reset(token)

    @contextmanager
    def use_trace(self, trace_id: str) -> Iterator[None]:
        token = _current_trace.set(trace_id)
        try:
            yield
        finally:
            _current_trace.reset(token)

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[SpanHandle]:
        trace_id = _current_trace.get() or self.start_trace("claim")
        handle = SpanHandle(
            id=new_id("sp"),
            trace_id=trace_id,
            parent_id=_current_span.get(),
            name=name,
            start=utcnow(),
            attributes=dict(attrs),
        )
        trace_token = _current_trace.set(trace_id)
        span_token = _current_span.set(handle.id)
        try:
            yield handle
        except BaseException as exc:
            if handle.status == "ok":
                handle.status = "error"
            handle.attributes.setdefault("error", f"{type(exc).__name__}: {exc}"[:500])
            raise
        finally:
            _current_span.reset(span_token)
            _current_trace.reset(trace_token)
            self._persist(handle)

    def _persist(self, h: SpanHandle) -> None:
        if self.db is None:
            return
        with self.db.session() as s:
            s.add(
                SpanRow(
                    id=h.id,
                    trace_id=h.trace_id,
                    parent_id=h.parent_id,
                    name=h.name,
                    start=h.start,
                    end=utcnow(),
                    status=h.status,
                    attributes=_jsonable(h.attributes),
                )
            )

    # --- queries ----------------------------------------------------------------------------------
    def get_trace(self, trace_id: str) -> Trace | None:
        if self.db is None:
            return None
        with self.db.session() as s:
            row = s.get(TraceRow, trace_id)
            if row is None:
                return None
            spans = s.scalars(
                select(SpanRow).where(SpanRow.trace_id == trace_id).order_by(SpanRow.start)
            ).all()
            return Trace(id=row.id, claim_id=row.claim_id, kind=row.kind, spans=[_to_span(r) for r in spans])  # type: ignore[arg-type]

    def list_traces(self, claim_id: str | None = None, limit: int = 100) -> list[Trace]:
        if self.db is None:
            return []
        with self.db.session() as s:
            q = select(TraceRow.id).order_by(TraceRow.created_at.desc()).limit(limit)
            if claim_id is not None:
                q = q.where(TraceRow.claim_id == claim_id)
            ids = s.scalars(q).all()
        return [t for t in (self.get_trace(i) for i in ids) if t is not None]

    def spans_since(self, since: dt.datetime) -> list[Span]:
        if self.db is None:
            return []
        with self.db.session() as s:
            rows = s.scalars(select(SpanRow).where(SpanRow.start >= since)).all()
            return [_to_span(r) for r in rows]


def _to_span(r: SpanRow) -> Span:
    return Span(
        id=r.id,
        trace_id=r.trace_id,
        parent_id=r.parent_id,
        name=r.name,
        start=r.start,
        end=r.end,
        status=r.status,  # type: ignore[arg-type]
        attributes=r.attributes,
    )


def _jsonable(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None or isinstance(v, str | int | float | bool | list | dict):
            out[k] = v
        else:
            out[k] = str(v)
    return out
