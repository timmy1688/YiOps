import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.config import get_settings
from app.connectors.kubeconfig import parse_kubeconfig
from app.connectors.registry import registry as connector_registry
from app.llm.deepseek import DeepSeekClient
from app.models import (
    AlertEvent,
    AlertIntegration,
    AnalysisModelConfig,
    AnalysisRun,
    DatasourceConfig,
    EvidenceItem,
    Incident,
    RootCauseReport,
    ToolExecution,
    UserFeedback,
    new_id,
)
from app.schemas import (
    AlertIntegrationCreate,
    AlertIntegrationRead,
    AlertIntegrationUpdate,
    AnalysisModelConfigRead,
    AnalysisModelConfigUpsert,
    AnalysisRunRead,
    ChatRequest,
    ChatResponse,
    DatasourceCreate,
    DatasourceRead,
    DatasourceUpdate,
    EvidenceRead,
    FeedbackCreate,
    FeedbackRead,
    IncidentRead,
    ManualIncidentCreate,
    RootCauseReportRead,
    ToolExecutionRead,
)
from app.security.credentials import CredentialVault
from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id, tenant_scope
from app.services.chat import CHAT_TOOLS, ChatToolRunner
from app.services.incidents import create_manual_incident, ingest_alertmanager

router = APIRouter()
settings = get_settings()
credential_vault = CredentialVault()


def _tenant_id() -> str:
    return current_tenant_id() or DEFAULT_TENANT_ID


@router.get("/health")
async def health() -> dict[str, str]:
    """Backward-compatible readiness endpoint."""
    await Incident.all().limit(1)
    return {"status": "ok"}


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Report that the API process is accepting requests."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    """Report that the API and its required database are ready."""
    try:
        await Incident.all().limit(1)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ready", "database": "ok"}


@router.post("/webhooks/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def alertmanager_webhook(
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    if settings.auth_enabled:
        raise HTTPException(
            status_code=403,
            detail="请使用系统设置中生成的带令牌 Alertmanager Webhook 地址",
        )
    with tenant_scope(DEFAULT_TENANT_ID):
        incidents = await ingest_alertmanager(payload, tenant_id=DEFAULT_TENANT_ID)
        analysis_run_ids = await _enqueue_analysis_runs(
            request,
            _firing_incidents(payload, incidents),
        )
    return {
        "incident_ids": list(dict.fromkeys(incident.id for incident in incidents)),
        "analysis_run_ids": analysis_run_ids,
    }


@router.get("/integrations", response_model=list[AlertIntegrationRead])
async def list_integrations() -> list[AlertIntegrationRead]:
    items = await AlertIntegration.filter(tenant_id=_tenant_id()).order_by("name")
    return [_integration_read(item) for item in items]


@router.post(
    "/integrations",
    response_model=AlertIntegrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(payload: AlertIntegrationCreate) -> AlertIntegrationRead:
    item = await AlertIntegration.create(
        id=new_id("integration"),
        tenant_id=_tenant_id(),
        webhook_token=secrets.token_urlsafe(24),
        **payload.model_dump(),
    )
    return _integration_read(item)


@router.patch("/integrations/{integration_id}", response_model=AlertIntegrationRead)
async def update_integration(
    integration_id: str,
    payload: AlertIntegrationUpdate,
) -> AlertIntegrationRead:
    item = await AlertIntegration.get_or_none(id=integration_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(item, key, value)
    await item.save()
    return _integration_read(item)


@router.delete(
    "/integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_integration(integration_id: str) -> Response:
    item = await AlertIntegration.get_or_none(id=integration_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    await item.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/integrations/{integration_id}/webhook/{token}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def integration_webhook(
    integration_id: str,
    token: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    item = await AlertIntegration.get_or_none(id=integration_id, webhook_token=token)
    if item is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not item.enabled:
        raise HTTPException(status_code=403, detail="Integration is disabled")

    with tenant_scope(item.tenant_id):
        incidents = await ingest_alertmanager(
            payload,
            tenant_id=item.tenant_id,
            default_cluster=item.default_cluster,
            default_namespace=item.default_namespace,
        )
        incident_ids = list(dict.fromkeys(incident.id for incident in incidents))
        analysis_run_ids = (
            await _enqueue_analysis_runs(
                request,
                _firing_incidents(payload, incidents),
            )
            if item.auto_analyze
            else []
        )

    item.received_count += len(payload.get("alerts", []))
    item.last_received_at = datetime.now(UTC)
    await item.save(
        update_fields=["received_count", "last_received_at", "updated_at"],
    )
    return {
        "incident_ids": incident_ids,
        "analysis_run_ids": analysis_run_ids,
        "analysis_required": "automatic" if item.auto_analyze else "manual",
    }


@router.get("/model-configs", response_model=list[AnalysisModelConfigRead])
async def list_model_configs() -> list[AnalysisModelConfigRead]:
    items = await AnalysisModelConfig.filter(tenant_id=_tenant_id()).order_by(
        "-enabled", "name"
    )
    return [_model_config_read(item) for item in items]


@router.post(
    "/model-configs",
    response_model=AnalysisModelConfigRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_model_config(
    payload: AnalysisModelConfigUpsert,
) -> AnalysisModelConfigRead:
    api_key = payload.api_key.strip() if payload.api_key else ""
    if not api_key:
        raise HTTPException(status_code=422, detail="新建渠道必须填写 API Key")

    values = payload.model_dump(exclude={"api_key"})
    values["base_url"] = str(payload.base_url).rstrip("/")
    try:
        async with in_transaction() as connection:
            if payload.enabled:
                await AnalysisModelConfig.filter(
                    tenant_id=_tenant_id(), enabled=True
                ).using_db(connection).update(enabled=False)
            item = await AnalysisModelConfig.create(
                id=new_id("model"),
                tenant_id=_tenant_id(),
                secret_ref=credential_vault.encrypt({"api_key": api_key}),
                using_db=connection,
                **values,
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="渠道名称已存在") from exc
    return _model_config_read(item)


@router.put("/model-configs/{config_id}", response_model=AnalysisModelConfigRead)
async def update_model_config(
    config_id: str,
    payload: AnalysisModelConfigUpsert,
) -> AnalysisModelConfigRead:
    item = await AnalysisModelConfig.get_or_none(id=config_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="模型渠道不存在")

    api_key = payload.api_key.strip() if payload.api_key else ""
    if not api_key and not item.secret_ref:
        raise HTTPException(status_code=422, detail="请填写 API Key")
    values = payload.model_dump(exclude={"api_key"})
    values["base_url"] = str(payload.base_url).rstrip("/")
    connection_changed = bool(api_key) or any(
        getattr(item, key) != value
        for key, value in values.items()
        if key in {"provider", "base_url", "model_name"}
    )
    try:
        async with in_transaction() as connection:
            if payload.enabled:
                await (
                    AnalysisModelConfig.filter(tenant_id=_tenant_id(), enabled=True)
                    .exclude(id=config_id)
                    .using_db(connection)
                    .update(enabled=False)
                )
            for key, value in values.items():
                setattr(item, key, value)
            if api_key:
                item.secret_ref = credential_vault.encrypt({"api_key": api_key})
            if connection_changed:
                item.update_from_dict(
                    {
                        "last_test_status": None,
                        "last_test_message": None,
                        "last_tested_at": None,
                    }
                )
            await item.save(using_db=connection)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="渠道名称已存在") from exc
    return _model_config_read(item)


@router.delete("/model-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_config(config_id: str) -> Response:
    deleted = await AnalysisModelConfig.filter(id=config_id, tenant_id=_tenant_id()).delete()
    if not deleted:
        raise HTTPException(status_code=404, detail="模型渠道不存在")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/model-configs/{config_id}/test")
async def test_model_config_by_id(config_id: str) -> dict[str, Any]:
    item = await AnalysisModelConfig.get_or_none(id=config_id, tenant_id=_tenant_id())
    if item is None or not item.secret_ref:
        raise HTTPException(status_code=404, detail="请先保存模型渠道和 API Key")
    return await _test_model_config(item)


# Keep the original single-config endpoints for older clients. They now operate
# on the active channel, or the first saved channel when none is active.
@router.get("/model-config", response_model=AnalysisModelConfigRead | None)
async def get_model_config() -> AnalysisModelConfigRead | None:
    item = (
        await AnalysisModelConfig.filter(tenant_id=_tenant_id(), enabled=True)
        .order_by("-updated_at")
        .first()
    )
    if item is None:
        item = (
            await AnalysisModelConfig.filter(tenant_id=_tenant_id())
            .order_by("created_at")
            .first()
        )
    return _model_config_read(item) if item else None


@router.put("/model-config", response_model=AnalysisModelConfigRead)
async def upsert_model_config(
    payload: AnalysisModelConfigUpsert,
) -> AnalysisModelConfigRead:
    item = (
        await AnalysisModelConfig.filter(tenant_id=_tenant_id(), enabled=True)
        .order_by("-updated_at")
        .first()
    )
    if item is None:
        item = (
            await AnalysisModelConfig.filter(tenant_id=_tenant_id())
            .order_by("created_at")
            .first()
        )
    if item is None:
        return await create_model_config(payload)
    return await update_model_config(item.id, payload)


@router.post("/model-config/test")
async def test_model_config() -> dict[str, Any]:
    item = (
        await AnalysisModelConfig.filter(tenant_id=_tenant_id(), enabled=True)
        .order_by("-updated_at")
        .first()
    )
    if item is None:
        item = (
            await AnalysisModelConfig.filter(tenant_id=_tenant_id())
            .order_by("created_at")
            .first()
        )
    if item is None or not item.secret_ref:
        raise HTTPException(status_code=404, detail="请先保存模型渠道和 API Key")
    return await _test_model_config(item)


async def _test_model_config(item: AnalysisModelConfig) -> dict[str, Any]:
    credential = credential_vault.decrypt(item.secret_ref or "").get("api_key", "")
    if not credential:
        raise HTTPException(status_code=422, detail="API Key 无法读取，请重新填写")
    try:
        message = await DeepSeekClient.test_connection(
            api_key=credential,
            base_url=item.base_url,
            model_name=item.model_name,
        )
        item.last_test_status = "healthy"
        item.last_test_message = message
        ok = True
    except Exception as exc:
        message = str(exc)[:1000]
        item.last_test_status = "failed"
        item.last_test_message = message
        ok = False
    item.last_tested_at = datetime.now(UTC)
    await item.save(
        update_fields=[
            "last_test_status",
            "last_test_message",
            "last_tested_at",
            "updated_at",
        ]
    )
    return {"ok": ok, "message": message}


@router.post("/incidents", response_model=IncidentRead, status_code=status.HTTP_201_CREATED)
async def create_incident(payload: ManualIncidentCreate) -> IncidentRead:
    incident = await create_manual_incident(payload, tenant_id=_tenant_id())
    return await _incident_read(incident)


@router.get("/incidents", response_model=list[IncidentRead])
async def list_incidents(
    service: str | None = None,
    severity: str | None = None,
    incident_status: str | None = None,
    limit: int = 50,
) -> list[IncidentRead]:
    query = Incident.filter(tenant_id=_tenant_id())
    if service:
        query = query.filter(service=service)
    if severity:
        query = query.filter(severity=severity)
    if incident_status:
        query = query.filter(status=incident_status)
    incidents = await query.order_by("-started_at").limit(min(max(limit, 1), 200))
    return [await _incident_read(incident) for incident in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentRead)
async def get_incident(incident_id: str) -> IncidentRead:
    incident = await Incident.get_or_none(id=incident_id, tenant_id=_tenant_id())
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return await _incident_read(incident)


@router.post(
    "/incidents/{incident_id}/analysis-runs",
    response_model=AnalysisRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis_run(incident_id: str, request: Request) -> AnalysisRunRead:
    incident = await Incident.get_or_none(id=incident_id, tenant_id=_tenant_id())
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    active = (
        await AnalysisRun.filter(
            incident_id=incident_id,
            status__in=["queued", "running"],
        )
        .order_by("-created_at")
        .first()
    )
    if active is not None:
        return AnalysisRunRead.model_validate(active)
    run = await _new_analysis_run(incident_id)
    await request.app.state.supervisor.enqueue(run.id)
    return AnalysisRunRead.model_validate(run)


async def _new_analysis_run(incident_id: str) -> AnalysisRun:
    configured_model = (
        await AnalysisModelConfig.filter(tenant_id=_tenant_id(), enabled=True)
        .order_by("-updated_at")
        .first()
    )
    model_name = (
        configured_model.model_name
        if configured_model and configured_model.secret_ref
        else (
            settings.deepseek_model
            if not settings.llm_mock_mode and settings.deepseek_api_key
            else "local-evidence-rules"
        )
    )
    return await AnalysisRun.create(
        id=new_id("run"),
        incident_id=incident_id,
        status="queued",
        progress=0,
        model_name=model_name,
    )


async def _enqueue_analysis_runs(
    request: Request,
    incidents: list[Incident],
) -> list[str]:
    run_ids: list[str] = []
    seen_incidents: set[str] = set()
    for incident in incidents:
        if incident.id in seen_incidents or incident.status != "open":
            continue
        seen_incidents.add(incident.id)
        existing = await AnalysisRun.filter(incident_id=incident.id).exists()
        if existing:
            continue
        run = await _new_analysis_run(incident.id)
        await request.app.state.supervisor.enqueue(run.id)
        run_ids.append(run.id)
    return run_ids


def _firing_incidents(
    payload: dict[str, Any],
    incidents: list[Incident],
) -> list[Incident]:
    raw_alerts = payload.get("alerts", [])
    return [
        incident
        for incident, raw in zip(incidents, raw_alerts, strict=False)
        if str(raw.get("status", payload.get("status", "firing"))).lower()
        not in {"resolved", "closed"}
    ]


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunRead)
async def get_analysis_run(run_id: str) -> AnalysisRunRead:
    run = await AnalysisRun.get_or_none(id=run_id, incident__tenant_id=_tenant_id())
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return AnalysisRunRead.model_validate(run)


@router.post("/analysis-runs/{run_id}/retry", response_model=AnalysisRunRead)
async def retry_analysis_run(run_id: str, request: Request) -> AnalysisRunRead:
    run = await AnalysisRun.get_or_none(id=run_id, incident__tenant_id=_tenant_id())
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    if run.status not in {"failed_final", "failed_retryable"}:
        raise HTTPException(status_code=409, detail="Only failed runs can be retried")
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    run.completed_at = None
    await run.save()
    await request.app.state.supervisor.enqueue(run.id)
    return AnalysisRunRead.model_validate(run)


@router.get("/analysis-runs/{run_id}/evidence", response_model=list[EvidenceRead])
async def list_evidence(run_id: str) -> list[EvidenceRead]:
    items = await EvidenceItem.filter(
        analysis_run_id=run_id,
        analysis_run__incident__tenant_id=_tenant_id(),
    ).order_by("-quality")
    return [EvidenceRead.model_validate(item) for item in items]


@router.get(
    "/analysis-runs/{run_id}/tool-executions",
    response_model=list[ToolExecutionRead],
)
async def list_tool_executions(run_id: str) -> list[ToolExecutionRead]:
    items = await ToolExecution.filter(
        analysis_run_id=run_id,
        analysis_run__incident__tenant_id=_tenant_id(),
    ).order_by("created_at")
    return [ToolExecutionRead.model_validate(item) for item in items]


@router.get("/analysis-runs/{run_id}/report", response_model=RootCauseReportRead)
async def get_report(run_id: str) -> RootCauseReportRead:
    report = await RootCauseReport.get_or_none(
        analysis_run_id=run_id,
        analysis_run__incident__tenant_id=_tenant_id(),
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not ready")
    return RootCauseReportRead.model_validate(report)


@router.get("/analysis-runs/{run_id}/events")
async def analysis_events(run_id: str, request: Request) -> StreamingResponse:
    run = await AnalysisRun.get_or_none(id=run_id, incident__tenant_id=_tenant_id())
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    async def stream():
        snapshot = {
            "event": "snapshot",
            "data": {
                "run_id": run.id,
                "status": run.status,
                "node": run.current_step,
                "progress": run.progress,
            },
        }
        yield _sse(snapshot)
        if run.status in {"completed", "insufficient_evidence", "failed_final"}:
            return
        async for event in request.app.state.events.subscribe(run_id):
            if await request.is_disconnected():
                break
            yield _sse(event)
            if event["event"] in {"report.completed", "run.failed"}:
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/reports/{report_id}/feedback", response_model=FeedbackRead)
async def create_feedback(report_id: str, payload: FeedbackCreate) -> FeedbackRead:
    if (
        await RootCauseReport.get_or_none(
            id=report_id,
            analysis_run__incident__tenant_id=_tenant_id(),
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Report not found")
    feedback = await UserFeedback.create(
        id=new_id("feedback"),
        report_id=report_id,
        **payload.model_dump(),
    )
    return FeedbackRead.model_validate(feedback)


@router.post("/chat/completions", response_model=ChatResponse)
async def create_chat_completion(payload: ChatRequest, request: Request) -> ChatResponse:
    context = await _chat_context(payload.incident_id)
    runner = ChatToolRunner(request.app.state.datasource_client)
    try:
        result = await DeepSeekClient(settings).chat(
            [message.model_dump() for message in payload.messages],
            context,
            tools=CHAT_TOOLS,
            tool_executor=runner.execute,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"模型暂时无法回答：{str(exc)[:500]}",
        ) from exc
    return ChatResponse(
        content=result.content,
        model_name=result.model_name,
        context_scope=str(context["scope"]),
        tool_calls=result.tool_calls,
    )


@router.get("/datasources", response_model=list[DatasourceRead])
async def list_datasources() -> list[DatasourceRead]:
    items = await DatasourceConfig.filter(tenant_id=_tenant_id()).order_by("name")
    return [_datasource_read(item) for item in items]


@router.get("/connector-types")
async def list_connector_types() -> list[dict[str, object]]:
    return [item.public_dict() for item in connector_registry.all()]


@router.post("/datasources", response_model=DatasourceRead, status_code=201)
async def create_datasource(payload: DatasourceCreate, request: Request) -> DatasourceRead:
    secret_ref = payload.secret_ref
    base_url = str(payload.base_url).rstrip("/") if payload.base_url else ""
    datasource_settings = dict(payload.settings)
    if payload.type == "kubernetes":
        if payload.kubeconfig:
            try:
                parsed = parse_kubeconfig(payload.kubeconfig)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            base_url = parsed.server
            datasource_settings.update(
                {
                    "cluster_id": parsed.cluster_id,
                    "context_name": parsed.context_name,
                    "default_namespace": parsed.namespace,
                    "verify_ssl": parsed.verify_ssl,
                    "credential_source": "kubeconfig",
                }
            )
            secret_ref = request.app.state.datasource_client.vault.encrypt(parsed.credentials)
        else:
            cluster_id = str(payload.settings.get("cluster_id", "")).strip()
            token = (payload.credential or payload.secret_ref or "").strip()
            if not base_url or not cluster_id:
                raise HTTPException(
                    status_code=422,
                    detail="请上传 kubeconfig，或填写 API Server 和集群标识",
                )
            if not token:
                raise HTTPException(status_code=422, detail="Kubernetes Token 不能为空")
            secret_ref = request.app.state.datasource_client.vault.encrypt(
                {"token": token, "ca_cert": (payload.ca_cert or "").strip()}
            )
    elif not base_url:
        raise HTTPException(status_code=422, detail="数据源地址不能为空")
    item = await DatasourceConfig.create(
        id=new_id("ds"),
        tenant_id=_tenant_id(),
        name=payload.name,
        type=payload.type,
        base_url=base_url,
        secret_ref=secret_ref,
        settings=datasource_settings,
        enabled=payload.enabled,
    )
    return _datasource_read(item)


@router.patch("/datasources/{datasource_id}", response_model=DatasourceRead)
async def update_datasource(
    datasource_id: str,
    payload: DatasourceUpdate,
    request: Request,
) -> DatasourceRead:
    item = await DatasourceConfig.get_or_none(id=datasource_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    updates = payload.model_dump(exclude_unset=True)
    kubeconfig = updates.pop("kubeconfig", None)
    credential = updates.pop("credential", None)
    ca_cert = updates.pop("ca_cert", None)
    if item.type == "kubernetes":
        legacy_credential = updates.pop("secret_ref", None)
        if credential is None:
            credential = legacy_credential
    if kubeconfig is not None:
        if item.type != "kubernetes":
            raise HTTPException(status_code=422, detail="只有 Kubernetes 支持 kubeconfig")
        try:
            parsed = parse_kubeconfig(kubeconfig)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        updates["base_url"] = parsed.server
        updates["settings"] = {
            **item.settings,
            "cluster_id": parsed.cluster_id,
            "context_name": parsed.context_name,
            "default_namespace": parsed.namespace,
            "verify_ssl": parsed.verify_ssl,
            "credential_source": "kubeconfig",
        }
        updates["secret_ref"] = request.app.state.datasource_client.vault.encrypt(
            parsed.credentials
        )
    if "base_url" in updates:
        updates["base_url"] = str(updates["base_url"]).rstrip("/")
    if item.type == "kubernetes" and (credential is not None or ca_cert is not None):
        existing = request.app.state.datasource_client.vault.decrypt(item.secret_ref)
        if credential is not None:
            existing["token"] = credential.strip()
        if ca_cert is not None:
            existing["ca_cert"] = ca_cert.strip()
        updates["secret_ref"] = request.app.state.datasource_client.vault.encrypt(existing)
    for key, value in updates.items():
        setattr(item, key, value)
    await item.save()
    return _datasource_read(item)


@router.delete(
    "/datasources/{datasource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_datasource(datasource_id: str) -> Response:
    item = await DatasourceConfig.get_or_none(id=datasource_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    await item.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasources/{datasource_id}/test")
async def test_datasource(datasource_id: str, request: Request) -> dict[str, Any]:
    item = await DatasourceConfig.get_or_none(id=datasource_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    ok, message = await request.app.state.datasource_client.test_connection(item)
    item.last_test_status = "healthy" if ok else "failed"
    item.last_tested_at = datetime.now(UTC)
    await item.save(update_fields=["last_test_status", "last_tested_at", "updated_at"])
    return {"ok": ok, "message": message}


async def _incident_read(incident: Incident) -> IncidentRead:
    latest = await AnalysisRun.filter(incident_id=incident.id).order_by("-created_at").first()
    latest_alert = await AlertEvent.filter(incident_id=incident.id).order_by("-created_at").first()
    return IncidentRead(
        id=incident.id,
        title=incident.title,
        service=incident.service,
        cluster=incident.cluster,
        namespace=incident.namespace,
        severity=incident.severity,
        status=incident.status,
        started_at=incident.started_at,
        ended_at=incident.ended_at,
        alert_count=incident.alert_count,
        is_test=_is_test_alert(latest_alert),
        source=latest_alert.source if latest_alert else None,
        created_at=incident.created_at,
        latest_run=AnalysisRunRead.model_validate(latest) if latest else None,
    )


async def _chat_context(incident_id: str | None) -> dict[str, object]:
    datasources = await DatasourceConfig.filter(
        tenant_id=_tenant_id(), enabled=True
    ).order_by("type", "name")
    available_datasources = [
        {
            "name": item.name,
            "type": item.type,
            "settings": {
                key: value
                for key, value in item.settings.items()
                if key in {"cluster_id", "default_namespace", "index_alias"}
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
            evidence = await EvidenceItem.filter(analysis_run_id=latest_run.id).order_by(
                "-quality"
            ).limit(min(settings.max_evidence_items, 20))
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

    incidents = (
        await Incident.filter(tenant_id=_tenant_id()).order_by("-started_at").limit(20)
    )
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


def _is_test_alert(alert: AlertEvent | None) -> bool:
    if alert is None:
        return False
    marker = str(alert.labels.get("yiops_test", "")).lower()
    if marker in {"1", "true", "yes"}:
        return True
    content = json.dumps(
        {"labels": alert.labels, "annotations": alert.annotations},
        ensure_ascii=False,
    ).lower()
    return any(keyword in content for keyword in ("测试", "验证", "演示", "smoke test"))


def _datasource_read(item: DatasourceConfig) -> DatasourceRead:
    return DatasourceRead(
        id=item.id,
        name=item.name,
        type=item.type,
        base_url=item.base_url,
        secret_configured=bool(item.secret_ref),
        settings=item.settings,
        enabled=item.enabled,
        last_test_status=item.last_test_status,
        last_tested_at=item.last_tested_at,
    )


def _integration_read(item: AlertIntegration) -> AlertIntegrationRead:
    return AlertIntegrationRead(
        id=item.id,
        name=item.name,
        type=item.type,
        webhook_path=(f"{settings.api_prefix}/integrations/{item.id}/webhook/{item.webhook_token}"),
        default_cluster=item.default_cluster,
        default_namespace=item.default_namespace,
        auto_analyze=item.auto_analyze,
        enabled=item.enabled,
        received_count=item.received_count,
        last_received_at=item.last_received_at,
        created_at=item.created_at,
    )


def _model_config_read(item: AnalysisModelConfig) -> AnalysisModelConfigRead:
    return AnalysisModelConfigRead(
        id=item.id,
        name=item.name,
        provider=item.provider,
        base_url=item.base_url,
        model_name=item.model_name,
        api_key_configured=bool(item.secret_ref),
        enabled=item.enabled,
        last_test_status=item.last_test_status,
        last_test_message=item.last_test_message,
        last_tested_at=item.last_tested_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"event: {payload['event']}\ndata: {json.dumps(payload['data'], ensure_ascii=False)}\n\n"
