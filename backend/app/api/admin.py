"""Admin API: metrics, traces, audit trail, labels, policies/rulesets, eval runs (bearer-token gated)."""

import asyncio
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.claims import audit_rows
from app.api.deps import Container, container, require_admin
from app.api.events import SSE_HEADERS
from app.api.schemas import AuditRow, EvalRunIn, PolicyIn, PolicyOut, RuleSetOut, TraceSummary
from app.domain.models import CorrectionLabel, EvalRun, Ticket, Trace
from app.evaluation.runner import run_eval
from app.observability import metrics
from app.rules.compiler import compile_policy
from app.rules.dsl import RuleSet

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
EVAL_TOPIC = "admin:eval"
_eval_tasks: dict[int, asyncio.Task[None]] = {}  # one running eval per app container


def _ruleset_out(ruleset: RuleSet, active: bool) -> RuleSetOut:
    return RuleSetOut(**ruleset.model_dump(by_alias=True), active=active)


@router.get("/metrics/overview")
def metrics_overview(days: int = Query(30, ge=1, le=365), c: Container = Depends(container)):
    now = c.orchestrator.clock()
    out = metrics.overview(
        claims=c.repo.list_claims(),
        spans=c.tracer.spans_since(now - dt.timedelta(days=days)),
        eval_runs=c.repo.list_eval_runs(),
        ruleset=c.repo.active_ruleset(),
        days=days,
        now=now,
        impact=c.settings.impact,
        fx_usd_inr=c.settings.FX_USD_INR,
    )
    return {**out, "assumptions": c.settings.impact.model_dump()}


# What a claim trace covers, from its first span (upload batch, re-check after answers, submit).
TRACE_STEP = {
    "ingest": " · upload",
    "extract": " · upload",
    "rules": " · re-check",
    "submit": " · submit",
    "ticket": " · ticket",
}


@router.get("/traces", response_model=list[TraceSummary])
def traces(claim_id: str | None = None, c: Container = Depends(container)):
    titles = {cl.id: cl.title for cl in c.repo.list_claims()}
    out = []
    for t in c.tracer.list_traces(claim_id):
        if not t.spans:
            continue
        start, end = min(s.start for s in t.spans), max(s.end for s in t.spans)
        statuses = {s.status for s in t.spans}
        out.append(
            TraceSummary(
                id=t.id,
                claim_id=t.claim_id,
                kind=t.kind,
                title=titles.get(t.claim_id or "", "Policy compile" if t.kind == "policy" else t.kind.title())
                + TRACE_STEP.get(t.spans[0].name, ""),
                started_at=start,
                duration_ms=int((end - start).total_seconds() * 1000),
                span_count=len(t.spans),
                status="error" if "error" in statuses else "retry" if "retry" in statuses else "ok",
                cost_usd=round(
                    sum(float(s.attributes.get("cost_usd") or 0) for s in t.spans if s.name == "llm"), 6
                ),
            )
        )
    return out


@router.get("/traces/{trace_id}", response_model=Trace)
def trace(trace_id: str, c: Container = Depends(container)):
    found = c.tracer.get_trace(trace_id)
    if found is None:
        raise HTTPException(404, f"trace {trace_id} not found")
    return found


@router.get("/audit", response_model=list[AuditRow])
def audit(c: Container = Depends(container)):
    rulesets = {rs.version: rs for rs, _ in c.repo.list_rulesets()}
    rows = [row for cl in c.repo.list_claims() for row in audit_rows(cl, rulesets.get(cl.ruleset_version))]
    return sorted(rows, key=lambda r: r.created_at, reverse=True)


@router.get("/tickets", response_model=list[Ticket])
def tickets(c: Container = Depends(container)):
    now = c.orchestrator.clock()
    rows = [c.finance.poll_ticket(t, now) for cl in c.repo.list_claims() for t in cl.tickets]
    return sorted(rows, key=lambda t: t.created_at, reverse=True)


@router.get("/labels", response_model=list[CorrectionLabel])
def labels(c: Container = Depends(container)):
    return c.repo.list_labels()


@router.get("/policies", response_model=list[PolicyOut])
def policies(c: Container = Depends(container)):
    rulesets = c.repo.list_rulesets()
    out = []
    for p in c.repo.list_policies():
        mine = [(rs.version, active) for rs, active in rulesets if rs.policy_id == p.id]
        out.append(
            PolicyOut(
                **p.model_dump(),
                ruleset_versions=[v for v, _ in mine],
                active_ruleset_version=next((v for v, active in mine if active), None),
            )
        )
    return out


@router.post("/policies", response_model=RuleSetOut)
async def compile_new_policy(body: PolicyIn, c: Container = Depends(container)):
    with c.tracer.trace("policy"), c.tracer.span("compile", name=body.name, chars=len(body.text)) as span:
        ruleset, dropped = await compile_policy(c.llm, c.repo, body.name, body.text, c.orchestrator.clock())
        span.set(version=ruleset.version, rules=len(ruleset.rules), dropped=dropped)
    return _ruleset_out(ruleset, True)


@router.get("/rulesets/{version}", response_model=RuleSetOut)
def ruleset(version: int, c: Container = Depends(container)):
    active = c.repo.active_ruleset()
    return _ruleset_out(c.repo.get_ruleset(version), active is not None and active.version == version)


@router.post("/rulesets/{version}/activate", response_model=RuleSetOut)
def activate(version: int, c: Container = Depends(container)):
    return _ruleset_out(c.repo.activate_ruleset(version), True)


@router.get("/eval/runs", response_model=list[EvalRun])
def eval_runs(c: Container = Depends(container)):
    return c.repo.list_eval_runs()


@router.get("/eval/runs/{run_id}", response_model=EvalRun)
def eval_run(run_id: str, c: Container = Depends(container)):
    return c.repo.get_eval_run(run_id)


async def _run_eval(c: Container, subset: str) -> None:
    def progress(done: int, total: int, fixture_id: str | None) -> None:
        data = {"done": done, "total": total} | ({"fixture_id": fixture_id} if fixture_id else {})
        c.broker.publish(EVAL_TOPIC, "progress", data)

    try:
        run = await run_eval(c.settings, subset, c.llm.provider, progress, created_at=c.orchestrator.clock())
    except Exception as exc:  # surfaced to the dashboard; the API process keeps serving
        c.broker.publish(EVAL_TOPIC, "error", {"message": f"Evaluation failed: {exc}"})
        return
    c.repo.save_eval_run(run)
    c.broker.publish(EVAL_TOPIC, "done", {"run": run})


@router.post("/eval/run", status_code=202)
async def start_eval(body: EvalRunIn | None = None, c: Container = Depends(container)):
    """Start an eval in the background; follow it on /admin/eval/events (progress, done, error)."""
    running = _eval_tasks.get(id(c))
    if running is not None and not running.done():
        raise HTTPException(409, "An evaluation is already running.")
    subset = (body or EvalRunIn()).subset
    _eval_tasks[id(c)] = asyncio.create_task(_run_eval(c, subset))
    return {"subset": subset, "status": "started"}


@router.get("/eval/events")
async def eval_events(request: Request, c: Container = Depends(container)):
    stream = c.broker.stream(EVAL_TOPIC, request.is_disconnected)
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)
