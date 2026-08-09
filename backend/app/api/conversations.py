import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.agents.tools import DatasourceToolExecutor
from app.api.dependencies import tenant_id as _tenant_id
from app.api.sse import encode_sse
from app.config import get_settings
from app.models import (
    AnalysisRun,
    ChatConversation,
    ChatConversationMessage,
    DatasourceConfig,
    EvidenceItem,
    Incident,
    RootCauseReport,
    new_id,
)
from app.schemas import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationImport,
    ChatConversationMessageCreate,
    ChatConversationMessageRead,
    ChatConversationRead,
    ChatConversationUpdate,
    ChatRequest,
    ChatResponse,
)

router = APIRouter()
settings = get_settings()


@router.post("/chat/completions", response_model=ChatResponse)
async def create_chat_completion(payload: ChatRequest, request: Request) -> ChatResponse:
    result, context = await _execute_chat(
        [message.model_dump() for message in payload.messages],
        payload.incident_id,
        request,
    )
    return ChatResponse(
        content=result.content,
        model_name=result.model_name,
        context_scope=str(context["scope"]),
        tool_calls=result.tool_calls,
    )


@router.get("/chat/conversations", response_model=list[ChatConversationRead])
async def list_chat_conversations() -> list[ChatConversationRead]:
    items = await ChatConversation.filter(tenant_id=_tenant_id()).order_by(
        "-last_message_at", "-updated_at"
    )
    return [await _chat_conversation_read(item) for item in items]


@router.post(
    "/chat/conversations",
    response_model=ChatConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_conversation(payload: ChatConversationCreate) -> ChatConversationDetail:
    if payload.incident_id and not await Incident.filter(
        id=payload.incident_id,
        tenant_id=_tenant_id(),
    ).exists():
        raise HTTPException(status_code=404, detail="Incident not found")
    title = (payload.title or "").strip() or "新对话"
    item = await ChatConversation.create(
        id=new_id("chat"),
        tenant_id=_tenant_id(),
        incident_id=payload.incident_id,
        title=title,
    )
    return await _chat_conversation_detail(item)


@router.post(
    "/chat/conversations/import",
    response_model=ChatConversationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def import_chat_conversation(payload: ChatConversationImport) -> ChatConversationDetail:
    if payload.incident_id and not await Incident.filter(
        id=payload.incident_id,
        tenant_id=_tenant_id(),
    ).exists():
        raise HTTPException(status_code=404, detail="Incident not found")
    first_user = next((item.content for item in payload.messages if item.role == "user"), "")
    title = (payload.title or "").strip() or " ".join(first_user.split())[:60] or "导入对话"
    item = await ChatConversation.create(
        id=new_id("chat"),
        tenant_id=_tenant_id(),
        incident_id=payload.incident_id,
        title=title,
    )
    for message in payload.messages:
        created = await ChatConversationMessage.create(
            id=new_id("cmsg"),
            conversation_id=item.id,
            role=message.role,
            content=message.content,
        )
        item.last_message_at = created.created_at
    await item.save(update_fields=["last_message_at", "updated_at"])
    return await _chat_conversation_detail(item)


@router.get(
    "/chat/conversations/{conversation_id}",
    response_model=ChatConversationDetail,
)
async def get_chat_conversation(conversation_id: str) -> ChatConversationDetail:
    return await _chat_conversation_detail(await _get_chat_conversation(conversation_id))


@router.patch(
    "/chat/conversations/{conversation_id}",
    response_model=ChatConversationRead,
)
async def update_chat_conversation(
    conversation_id: str,
    payload: ChatConversationUpdate,
) -> ChatConversationRead:
    item = await _get_chat_conversation(conversation_id)
    item.title = payload.title.strip()
    await item.save(update_fields=["title", "updated_at"])
    return await _chat_conversation_read(item)


@router.delete(
    "/chat/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_chat_conversation(conversation_id: str) -> Response:
    await (await _get_chat_conversation(conversation_id)).delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/chat/conversations/{conversation_id}/messages",
    response_model=ChatResponse,
)
async def create_chat_conversation_message(
    conversation_id: str,
    payload: ChatConversationMessageCreate,
    request: Request,
) -> ChatResponse:
    conversation = await _get_chat_conversation(conversation_id)
    return await _run_chat_conversation_turn(conversation, payload.content, request)


@router.post("/chat/conversations/{conversation_id}/messages/stream")
async def stream_chat_conversation_message(
    conversation_id: str,
    payload: ChatConversationMessageCreate,
    request: Request,
) -> StreamingResponse:
    conversation = await _get_chat_conversation(conversation_id)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_token(content: str) -> None:
        await queue.put({"event": "token", "data": {"content": content}})

    async def run() -> None:
        try:
            response = await _run_chat_conversation_turn(
                conversation,
                payload.content,
                request,
                token_callback=on_token,
            )
            await queue.put({"event": "done", "data": response.model_dump(mode="json")})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            await queue.put(
                {
                    "event": "error",
                    "data": {"message": str(detail)[:500]},
                }
            )

    task = asyncio.create_task(run(), name=f"chat-stream-{conversation.id}")

    async def events() -> AsyncIterator[str]:
        yield encode_sse(
            {
                "event": "conversation",
                "data": {"conversation_id": conversation.id, "title": conversation.title},
            }
        )
        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield encode_sse({"event": "ping", "data": {"status": "running"}})
                    continue
                yield encode_sse(event)
                if event["event"] in {"done", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_chat_conversation_turn(
    conversation: ChatConversation,
    raw_content: str,
    request: Request,
    *,
    token_callback: Callable[[str], Awaitable[None]] | None = None,
) -> ChatResponse:
    previous = (
        await ChatConversationMessage.filter(conversation_id=conversation.id)
        .order_by("-created_at")
        .limit(23)
    )
    previous.reverse()
    content = raw_content.strip()
    user_message = await ChatConversationMessage.create(
        id=new_id("cmsg"),
        conversation_id=conversation.id,
        role="user",
        content=content,
    )
    messages = [
        {"role": item.role, "content": item.content}
        for item in previous
        if item.role in {"user", "assistant"}
    ]
    messages.append({"role": "user", "content": content})
    result, context = await _execute_chat(
        messages,
        conversation.incident_id,
        request,
        token_callback=token_callback,
    )
    assistant_message = await ChatConversationMessage.create(
        id=new_id("cmsg"),
        conversation_id=conversation.id,
        role="assistant",
        content=result.content,
        model_name=result.model_name,
        tool_calls=result.tool_calls,
    )
    if conversation.title == "新对话" and not previous:
        conversation.title = " ".join(content.split())[:60] or "新对话"
    conversation.last_message_at = assistant_message.created_at or user_message.created_at
    await conversation.save(update_fields=["title", "last_message_at", "updated_at"])
    return ChatResponse(
        content=result.content,
        model_name=result.model_name,
        context_scope=str(context["scope"]),
        tool_calls=result.tool_calls,
        conversation_id=conversation.id,
        conversation_title=conversation.title,
    )


async def _execute_chat(
    messages: list[dict[str, str]],
    incident_id: str | None,
    request: Request,
    *,
    token_callback: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[Any, dict[str, object]]:
    context = await _chat_context(incident_id)
    query = " ".join(str(message.get("content", "")) for message in messages[-3:])
    incident = context.get("incident")
    if isinstance(incident, dict):
        query = " ".join(
            [str(incident.get("title", "")), str(incident.get("service", "")), query]
        )
    context["retrieved_memory"] = [
        item.public_dict() for item in await request.app.state.memory.retrieve(query)
    ]
    runner = DatasourceToolExecutor(request.app.state.datasource_gateway, context)
    try:
        result = await request.app.state.conversation_agent.run(
            messages,
            context,
            tool_executor=runner.execute,
            token_callback=token_callback,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"模型暂时无法回答：{str(exc)[:500]}",
        ) from exc
    return result, context


async def _get_chat_conversation(conversation_id: str) -> ChatConversation:
    item = await ChatConversation.get_or_none(id=conversation_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="对话不存在或已删除")
    return item


async def _chat_conversation_read(item: ChatConversation) -> ChatConversationRead:
    return ChatConversationRead(
        id=item.id,
        title=item.title,
        incident_id=item.incident_id,
        message_count=await ChatConversationMessage.filter(conversation_id=item.id).count(),
        last_message_at=item.last_message_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _chat_conversation_detail(item: ChatConversation) -> ChatConversationDetail:
    summary = await _chat_conversation_read(item)
    messages = await ChatConversationMessage.filter(conversation_id=item.id).order_by("created_at")
    return ChatConversationDetail(
        **summary.model_dump(),
        messages=[ChatConversationMessageRead.model_validate(message) for message in messages],
    )


async def _chat_context(incident_id: str | None) -> dict[str, object]:
    datasources = await DatasourceConfig.filter(tenant_id=_tenant_id(), enabled=True).order_by(
        "type", "name"
    )
    available_datasources = [
        {
            "name": item.name,
            "type": item.type,
            "settings": {
                key: value
                for key, value in item.settings.items()
                if key in {"cluster_id", "default_namespace", "index_alias", "tenant_id"}
            },
        }
        for item in datasources
    ]
    if incident_id:
        incident = await Incident.get_or_none(id=incident_id, tenant_id=_tenant_id())
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        latest_run = (
            await AnalysisRun.filter(incident_id=incident.id).order_by("-created_at").first()
        )
        context: dict[str, object] = {
            "scope": "incident",
            "available_datasources": available_datasources,
            "incident": {
                "id": incident.id,
                "title": incident.title,
                "service": incident.service,
                "cluster": incident.cluster,
                "namespace": incident.namespace,
                "severity": incident.severity,
                "status": incident.status,
                "started_at": incident.started_at.isoformat(),
                "ended_at": incident.ended_at.isoformat() if incident.ended_at else None,
                "alert_count": incident.alert_count,
            },
        }
        if latest_run:
            context["analysis"] = {
                "status": latest_run.status,
                "current_step": latest_run.current_step,
                "progress": latest_run.progress,
                "model_name": latest_run.model_name,
                "error_message": latest_run.error_message,
            }
            evidence = (
                await EvidenceItem.filter(analysis_run_id=latest_run.id)
                .order_by("-quality")
                .limit(min(settings.max_evidence_items, 20))
            )
            context["evidence"] = [
                {
                    "id": item.id,
                    "source": item.source,
                    "type": item.type,
                    "title": item.title,
                    "summary": item.summary,
                    "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                    "quality": item.quality,
                    "values": item.values,
                }
                for item in evidence
            ]
            report = await RootCauseReport.get_or_none(analysis_run_id=latest_run.id)
            if report:
                context["report"] = {
                    "status": report.status,
                    "summary": report.summary,
                    "confidence": report.confidence,
                    "hypotheses": report.hypotheses,
                    "recommended_actions": report.recommended_actions,
                    "missing_evidence": report.missing_evidence,
                }
        return context

    incidents = await Incident.filter(tenant_id=_tenant_id()).order_by("-started_at").limit(20)
    return {
        "scope": "overview",
        "available_datasources": available_datasources,
        "recent_incidents": [
            {
                "id": item.id,
                "title": item.title,
                "service": item.service,
                "cluster": item.cluster,
                "namespace": item.namespace,
                "severity": item.severity,
                "status": item.status,
                "started_at": item.started_at.isoformat(),
                "alert_count": item.alert_count,
            }
            for item in incidents
        ],
    }
