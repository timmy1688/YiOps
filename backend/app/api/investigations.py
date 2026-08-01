import json
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.models import (
    Incident,
    Investigation,
    InvestigationEvidence,
    InvestigationHypothesis,
    InvestigationMessage,
    InvestigationStep,
    new_id,
)
from app.schemas import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationEvidenceRead,
    InvestigationHypothesisRead,
    InvestigationMessageCreate,
    InvestigationMessageRead,
    InvestigationRead,
    InvestigationShareRead,
    InvestigationStepRead,
)
from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id

router = APIRouter(tags=["investigations"])
TERMINAL = {"completed", "cancelled", "failed"}


def _tenant_id() -> str:
    return current_tenant_id() or DEFAULT_TENANT_ID


@router.get("/investigations", response_model=list[InvestigationRead])
async def list_investigations() -> list[InvestigationRead]:
    items = (
        await Investigation.filter(tenant_id=_tenant_id()).order_by("-updated_at").limit(200)
    )
    return [InvestigationRead.model_validate(item) for item in items]


@router.post(
    "/investigations",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_investigation(payload: InvestigationCreate, request: Request) -> InvestigationRead:
    if (
        payload.incident_id
        and await Incident.get_or_none(id=payload.incident_id, tenant_id=_tenant_id()) is None
    ):
        raise HTTPException(status_code=404, detail="Incident not found")
    item = await Investigation.create(
        id=new_id("inv"),
        tenant_id=_tenant_id(),
        incident_id=payload.incident_id,
        title=payload.title,
        status="queued",
        current_step="等待 Agent 调度",
    )
    await InvestigationMessage.create(
        id=new_id("msg"),
        investigation_id=item.id,
        role="user",
        content=payload.question,
    )
    await request.app.state.investigation_supervisor.enqueue(item.id)
    return InvestigationRead.model_validate(item)


@router.get("/investigations/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation(investigation_id: str) -> InvestigationDetail:
    return await _detail(investigation_id)


@router.post(
    "/investigations/{investigation_id}/messages",
    response_model=InvestigationRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_investigation_message(
    investigation_id: str,
    payload: InvestigationMessageCreate,
    request: Request,
) -> InvestigationRead:
    item = await _get(investigation_id)
    if item.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Investigation is already running")
    await InvestigationMessage.create(
        id=new_id("msg"),
        investigation_id=item.id,
        role="user",
        content=payload.content,
    )
    item.status = "queued"
    item.current_step = "等待 Agent 调度"
    item.progress = 0.0
    item.completed_at = None
    item.error_code = None
    item.error_message = None
    await item.save()
    await request.app.state.investigation_supervisor.enqueue(item.id)
    return InvestigationRead.model_validate(item)


@router.post(
    "/investigations/{investigation_id}/cancel",
    response_model=InvestigationRead,
)
async def cancel_investigation(investigation_id: str, request: Request) -> InvestigationRead:
    item = await _get(investigation_id)
    if item.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Investigation is not running")
    await request.app.state.investigation_supervisor.cancel(item.id)
    return InvestigationRead.model_validate(await Investigation.get(id=item.id))


@router.post(
    "/investigations/{investigation_id}/resume",
    response_model=InvestigationRead,
)
async def resume_investigation(investigation_id: str, request: Request) -> InvestigationRead:
    item = await _get(investigation_id)
    if item.status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=409, detail="Only cancelled or failed work can resume")
    item.status = "queued"
    item.current_step = "等待 Agent 继续调查"
    item.completed_at = None
    item.error_code = None
    item.error_message = None
    await item.save()
    await request.app.state.investigation_supervisor.enqueue(item.id)
    return InvestigationRead.model_validate(item)


@router.post(
    "/investigations/{investigation_id}/share",
    response_model=InvestigationShareRead,
)
async def share_investigation(investigation_id: str) -> InvestigationShareRead:
    item = await _get(investigation_id)
    if not item.share_token:
        item.share_token = secrets.token_urlsafe(24)
        await item.save(update_fields=["share_token", "updated_at"])
    return InvestigationShareRead(
        share_token=item.share_token,
        share_path=f"/api/v1/shared/investigations/{item.share_token}",
    )


@router.delete("/investigations/{investigation_id}/share", status_code=204)
async def revoke_investigation_share(investigation_id: str) -> Response:
    item = await _get(investigation_id)
    item.share_token = None
    await item.save(update_fields=["share_token", "updated_at"])
    return Response(status_code=204)


@router.get("/shared/investigations/{share_token}", response_model=InvestigationDetail)
async def get_shared_investigation(share_token: str) -> InvestigationDetail:
    item = await Investigation.get_or_none(share_token=share_token)
    if item is None:
        raise HTTPException(status_code=404, detail="Shared investigation not found")
    return await _detail(item.id, enforce_tenant=False)


@router.get("/investigations/{investigation_id}/export")
async def export_investigation(investigation_id: str) -> PlainTextResponse:
    detail = await _detail(investigation_id)
    markdown = _markdown(detail)
    filename = f"yiops-investigation-{investigation_id}.md"
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/investigations/{investigation_id}/events")
async def investigation_events(investigation_id: str, request: Request) -> StreamingResponse:
    item = await _get(investigation_id)

    async def stream() -> AsyncIterator[str]:
        yield _sse(
            "snapshot",
            {
                "run_id": item.id,
                "status": item.status,
                "current_step": item.current_step,
                "progress": item.progress,
            },
        )
        if item.status in TERMINAL:
            return
        async for event in request.app.state.events.subscribe(item.id):
            if await request.is_disconnected():
                break
            yield _sse(event["event"], event["data"])
            if event["event"] in {
                "investigation.completed",
                "investigation.cancelled",
                "investigation.failed",
            }:
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _get(investigation_id: str, *, enforce_tenant: bool = True) -> Investigation:
    filters = {"id": investigation_id}
    if enforce_tenant:
        filters["tenant_id"] = _tenant_id()
    item = await Investigation.get_or_none(**filters)
    if item is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return item


async def _detail(
    investigation_id: str,
    *,
    enforce_tenant: bool = True,
) -> InvestigationDetail:
    item = await _get(investigation_id, enforce_tenant=enforce_tenant)
    messages = await InvestigationMessage.filter(investigation_id=investigation_id).order_by(
        "created_at"
    )
    steps = await InvestigationStep.filter(investigation_id=investigation_id).order_by("sequence")
    evidence = await InvestigationEvidence.filter(investigation_id=investigation_id).order_by(
        "-quality", "created_at"
    )
    hypotheses = await InvestigationHypothesis.filter(investigation_id=investigation_id).order_by(
        "-confidence"
    )
    return InvestigationDetail(
        **InvestigationRead.model_validate(item).model_dump(),
        messages=[InvestigationMessageRead.model_validate(value) for value in messages],
        steps=[InvestigationStepRead.model_validate(value) for value in steps],
        evidence=[InvestigationEvidenceRead.model_validate(value) for value in evidence],
        hypotheses=[InvestigationHypothesisRead.model_validate(value) for value in hypotheses],
    )


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _markdown(detail: InvestigationDetail) -> str:
    lines = [
        f"# {detail.title}",
        "",
        f"- 调查 ID：`{detail.id}`",
        f"- 状态：`{detail.status}`",
        f"- 模型：`{detail.model_name or '-'}`",
        f"- 创建时间：{detail.created_at.isoformat()}",
        "",
        "## 分析结论",
        "",
        detail.summary or "尚未形成结论。",
        "",
        "## 假设",
        "",
    ]
    for item in detail.hypotheses:
        lines.append(f"- **{item.confidence:.0%}** {item.cause}（{item.status}）")
    if not detail.hypotheses:
        lines.append("- 暂无结构化假设")
    lines.extend(["", "## 证据", ""])
    for item in detail.evidence:
        lines.append(f"- `{item.source}` **{item.title}**：{item.summary}")
    if not detail.evidence:
        lines.append("- 暂无证据")
    lines.extend(["", "## 调查时间线", ""])
    for step in detail.steps:
        lines.append(
            f"- {step.created_at.isoformat()} `{step.status}` {step.description or step.name} "
            f"（{step.result_count} 条，{step.duration_ms} ms）"
        )
    lines.extend(["", "## 对话", ""])
    for message in detail.messages:
        role = "用户" if message.role == "user" else "Agent"
        lines.extend([f"### {role}", "", message.content, ""])
    return "\n".join(lines)
