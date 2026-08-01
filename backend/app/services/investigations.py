import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from app.analysis.evidence import redact
from app.connectors.client import DatasourceClient
from app.llm.deepseek import DeepSeekClient
from app.models import (
    EvidenceItem,
    Incident,
    Investigation,
    InvestigationEvent,
    InvestigationEvidence,
    InvestigationHypothesis,
    InvestigationMessage,
    InvestigationStep,
    RootCauseReport,
    new_id,
)
from app.runtime.events import EventBroker
from app.security.tenant import set_tenant_id
from app.services.chat import CHAT_TOOLS, ChatToolRunner

TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


class InvestigationRunner:
    """Run an evidence-grounded chat turn and persist its full audit trail."""

    def __init__(
        self,
        datasource_client: DatasourceClient,
        llm: DeepSeekClient,
        events: EventBroker,
    ) -> None:
        self.datasource_client = datasource_client
        self.llm = llm
        self.events = events

    async def run(self, investigation_id: str) -> None:
        investigation = await Investigation.get(id=investigation_id)
        # Supervisor workers are long-lived tasks; set the workspace before every run.
        set_tenant_id(investigation.tenant_id)
        now = datetime.now(UTC)
        investigation.status = "running"
        investigation.current_step = "理解问题与规划取证"
        investigation.progress = 0.1
        investigation.started_at = investigation.started_at or now
        investigation.completed_at = None
        investigation.error_code = None
        investigation.error_message = None
        await investigation.save()
        await self._event(investigation_id, "investigation.started", {"progress": 0.1})

        messages = (
            await InvestigationMessage.filter(investigation_id=investigation_id)
            .order_by("-created_at")
            .limit(24)
        )
        messages.reverse()
        context = await self._context(investigation)
        tool_runner = ChatToolRunner(self.datasource_client)

        async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            current = await Investigation.get(id=investigation_id)
            if current.status == "cancelled":
                raise asyncio.CancelledError
            sequence = await InvestigationStep.filter(investigation_id=investigation_id).count() + 1
            step = await InvestigationStep.create(
                id=new_id("step"),
                investigation_id=investigation_id,
                sequence=sequence,
                name=name,
                source=_tool_source(name),
                status="running",
                description=_tool_description(name),
                parameters=_safe_json(arguments),
            )
            current.current_step = _tool_description(name)
            current.progress = min(0.2 + sequence * 0.1, 0.78)
            await current.save(update_fields=["current_step", "progress", "updated_at"])
            await self._event(
                investigation_id,
                "step.started",
                {"step_id": step.id, "sequence": sequence, "name": name},
            )
            try:
                result = await tool_runner.execute(name, arguments)
            except asyncio.CancelledError:
                step.status = "cancelled"
                step.completed_at = datetime.now(UTC)
                await step.save()
                raise
            except Exception as exc:
                result = {
                    "name": name,
                    "status": "failed",
                    "result_count": 0,
                    "duration_ms": 0,
                    "parameters": arguments,
                    "error_code": type(exc).__name__,
                    "data": {"message": str(exc)[:500]},
                }
            step.status = str(result.get("status", "failed"))
            step.result_count = int(result.get("result_count", 0))
            step.duration_ms = int(result.get("duration_ms", 0))
            step.error_code = _optional(result.get("error_code"))
            step.parameters = _safe_json(result.get("parameters", arguments))
            step.completed_at = datetime.now(UTC)
            await step.save()
            if step.status == "completed" and step.result_count > 0:
                await self._save_tool_evidence(investigation_id, step, result)
            await self._event(
                investigation_id,
                "step.completed",
                {
                    "step_id": step.id,
                    "status": step.status,
                    "result_count": step.result_count,
                    "duration_ms": step.duration_ms,
                },
            )
            return result

        try:
            result = await self.llm.chat(
                [{"role": item.role, "content": item.content} for item in messages],
                context,
                tools=CHAT_TOOLS,
                tool_executor=execute,
            )
            await InvestigationMessage.create(
                id=new_id("msg"),
                investigation_id=investigation_id,
                role="assistant",
                content=result.content,
                model_name=result.model_name,
                tool_calls=result.tool_calls,
            )
            await self._sync_incident_evidence(investigation)
            await self._sync_hypotheses(investigation)
            await self._ensure_hypothesis(investigation, result.content)
            investigation = await Investigation.get(id=investigation_id)
            investigation.status = "completed"
            investigation.current_step = "形成结论"
            investigation.progress = 1.0
            investigation.model_name = result.model_name
            investigation.summary = result.content
            investigation.input_tokens += result.input_tokens
            investigation.output_tokens += result.output_tokens
            investigation.tool_count += len(result.tool_calls)
            investigation.completed_at = datetime.now(UTC)
            await investigation.save()
            await self._event(
                investigation_id,
                "investigation.completed",
                {"progress": 1.0, "model_name": result.model_name},
            )
        except asyncio.CancelledError:
            current = await Investigation.get_or_none(id=investigation_id)
            if current is not None and current.status != "cancelled":
                current.status = "queued"
                current.current_step = "等待服务恢复后继续"
                current.completed_at = None
                await current.save()
                await self._event(investigation_id, "investigation.interrupted", {})
            raise
        except Exception as exc:
            investigation = await Investigation.get(id=investigation_id)
            investigation.status = "failed"
            investigation.error_code = type(exc).__name__
            investigation.error_message = str(exc)[:2000]
            investigation.completed_at = datetime.now(UTC)
            await investigation.save()
            await self._event(
                investigation_id,
                "investigation.failed",
                {"error_code": type(exc).__name__, "message": str(exc)[:500]},
            )

    async def cancel(self, investigation_id: str) -> None:
        investigation = await Investigation.get_or_none(id=investigation_id)
        if investigation is None or investigation.status in TERMINAL_STATUSES:
            return
        investigation.status = "cancelled"
        investigation.current_step = "已由用户取消"
        investigation.completed_at = datetime.now(UTC)
        await investigation.save()
        await InvestigationStep.filter(investigation_id=investigation_id, status="running").update(
            status="cancelled", completed_at=datetime.now(UTC)
        )
        await self._event(investigation_id, "investigation.cancelled", {})

    async def _context(self, investigation: Investigation) -> dict[str, object]:
        recent = await Incident.all().order_by("-started_at").limit(12)
        context: dict[str, object] = {
            "scope": "investigation",
            "investigation": {"id": investigation.id, "title": investigation.title},
            "recent_incidents": [
                {
                    "id": item.id,
                    "title": item.title,
                    "service": item.service,
                    "severity": item.severity,
                    "status": item.status,
                    "started_at": item.started_at.isoformat(),
                }
                for item in recent
            ],
        }
        if investigation.incident_id:
            incident = await Incident.get(id=investigation.incident_id)
            context["scope"] = "incident"
            context["incident"] = {
                "id": incident.id,
                "title": incident.title,
                "service": incident.service,
                "cluster": incident.cluster,
                "namespace": incident.namespace,
                "severity": incident.severity,
                "status": incident.status,
                "started_at": incident.started_at.isoformat(),
            }
        return context

    async def _save_tool_evidence(
        self,
        investigation_id: str,
        step: InvestigationStep,
        result: dict[str, Any],
    ) -> None:
        data = _compact_data(result.get("data", {}))
        summary = _evidence_summary(step.name, step.result_count, data)
        await InvestigationEvidence.create(
            id=new_id("ive"),
            investigation_id=investigation_id,
            step_id=step.id,
            source=step.source,
            title=_tool_description(step.name),
            summary=summary,
            subject={"tool": step.name},
            values=data,
            quality=0.9,
        )

    async def _sync_incident_evidence(self, investigation: Investigation) -> None:
        if not investigation.incident_id:
            return
        latest_report = (
            await RootCauseReport.filter(analysis_run__incident_id=investigation.incident_id)
            .order_by("-created_at")
            .first()
        )
        if latest_report is None:
            return
        items = (
            await EvidenceItem.filter(analysis_run_id=latest_report.analysis_run_id)
            .order_by("-quality")
            .limit(30)
        )
        existing = {
            item.title
            for item in await InvestigationEvidence.filter(investigation_id=investigation.id).all()
        }
        for item in items:
            if item.title in existing:
                continue
            await InvestigationEvidence.create(
                id=new_id("ive"),
                investigation_id=investigation.id,
                source=item.source,
                title=item.title,
                summary=redact(item.summary),
                observed_at=item.observed_at,
                subject=_safe_json(item.subject),
                values=_safe_json(item.values),
                quality=item.quality,
            )

    async def _sync_hypotheses(self, investigation: Investigation) -> None:
        if not investigation.incident_id:
            return
        report = (
            await RootCauseReport.filter(analysis_run__incident_id=investigation.incident_id)
            .order_by("-created_at")
            .first()
        )
        if report is None:
            return
        await InvestigationHypothesis.filter(investigation_id=investigation.id).delete()
        for hypothesis in report.hypotheses:
            await InvestigationHypothesis.create(
                id=new_id("hyp"),
                investigation_id=investigation.id,
                cause=str(hypothesis.get("cause", "未知原因")),
                confidence=float(hypothesis.get("confidence", 0.0)),
                status=(
                    "leading" if float(hypothesis.get("confidence", 0.0)) >= 0.6 else "candidate"
                ),
                supporting_evidence_ids=hypothesis.get("supporting_evidence_ids", []),
                contradicting_evidence_ids=hypothesis.get("contradicting_evidence_ids", []),
                missing_evidence=hypothesis.get("missing_evidence", []),
            )

    async def _ensure_hypothesis(
        self, investigation: Investigation, assistant_content: str
    ) -> None:
        if await InvestigationHypothesis.filter(investigation_id=investigation.id).exists():
            return
        evidence = await InvestigationEvidence.filter(investigation_id=investigation.id).all()
        evidence_ids = [item.id for item in evidence]
        source_count = len({item.source for item in evidence})
        confidence = min(0.45 + source_count * 0.12, 0.85) if evidence else 0.25
        await InvestigationHypothesis.create(
            id=new_id("hyp"),
            investigation_id=investigation.id,
            cause=_extract_conclusion(assistant_content),
            confidence=confidence,
            status="leading" if confidence >= 0.6 else "candidate",
            supporting_evidence_ids=evidence_ids,
            missing_evidence=([] if source_count >= 2 else ["需要至少一个独立数据源交叉验证"]),
        )

    async def _event(self, investigation_id: str, event_type: str, payload: dict[str, Any]) -> None:
        await InvestigationEvent.create(
            id=new_id("evt"),
            investigation_id=investigation_id,
            event_type=event_type,
            payload=_safe_json(payload),
        )
        await self.events.publish(investigation_id, event_type, payload)


class InvestigationSupervisor:
    def __init__(self, runner: InvestigationRunner, concurrency: int) -> None:
        self.runner = runner
        self.concurrency = concurrency
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._running: dict[str, asyncio.Task[None]] = {}
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(), name=f"investigation-worker-{index}")
            for index in range(self.concurrency)
        ]
        pending = await Investigation.filter(status__in=["queued", "running"]).all()
        for investigation in pending:
            investigation.status = "queued"
            await investigation.save(update_fields=["status", "updated_at"])
            await self.enqueue(investigation.id)

    async def stop(self) -> None:
        for task in self._running.values():
            task.cancel()
        for worker in self._workers:
            worker.cancel()
        for task in [*self._running.values(), *self._workers]:
            with suppress(asyncio.CancelledError):
                await task
        self._running.clear()
        self._workers.clear()

    async def enqueue(self, investigation_id: str) -> None:
        if investigation_id in self._queued or investigation_id in self._running:
            return
        self._queued.add(investigation_id)
        await self.queue.put(investigation_id)

    async def cancel(self, investigation_id: str) -> None:
        await self.runner.cancel(investigation_id)
        task = self._running.get(investigation_id)
        if task:
            task.cancel()

    async def _worker(self) -> None:
        while True:
            investigation_id = await self.queue.get()
            self._queued.discard(investigation_id)
            try:
                investigation = await Investigation.get_or_none(id=investigation_id)
                if investigation is None or investigation.status == "cancelled":
                    continue
                task = asyncio.create_task(
                    self.runner.run(investigation_id),
                    name=f"investigation-{investigation_id}",
                )
                self._running[investigation_id] = task
                await task
            except asyncio.CancelledError:
                if asyncio.current_task() and asyncio.current_task().cancelling():
                    raise
            finally:
                self._running.pop(investigation_id, None)
                self.queue.task_done()


def _safe_json(value: Any) -> Any:
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    return json.loads(redact(serialized))


def _compact_data(value: Any) -> Any:
    """Keep investigation evidence useful without storing unbounded query payloads."""
    data = _safe_json(value)
    if not isinstance(data, dict):
        return data
    compact = {key: item for key, item in data.items() if key not in {"entries", "series", "items"}}
    entries = data.get("entries")
    if isinstance(entries, list):
        compact["entries"] = [
            {
                "timestamp": item.get("timestamp"),
                "labels": item.get("labels", {}),
                "line": str(item.get("line", ""))[:1000],
            }
            for item in entries[:20]
            if isinstance(item, dict)
        ]
    series = data.get("series")
    if isinstance(series, list):
        compact["series"] = []
        for item in series[:20]:
            if not isinstance(item, dict):
                continue
            values = item.get("values", [])
            samples = values if len(values) <= 6 else [*values[:3], *values[-3:]]
            compact["series"].append({"metric": item.get("metric", {}), "values": samples})
    items = data.get("items")
    if isinstance(items, list):
        compact["items"] = items[:20]
    serialized = json.dumps(compact, ensure_ascii=False, default=str)
    if len(serialized) > 100_000:
        return {"truncated": True, "preview": serialized[:100_000]}
    return compact


def _optional(value: Any) -> str | None:
    return str(value)[:120] if value else None


def _tool_source(name: str) -> str:
    if "loki" in name:
        return "loki"
    if "prometheus" in name:
        return "prometheus"
    if "kubernetes" in name:
        return "kubernetes"
    if "elasticsearch" in name:
        return "elasticsearch"
    return "yiops"


def _tool_description(name: str) -> str:
    return {
        "get_incident_analysis": "读取已有故障分析与证据",
        "query_loki_logs": "查询 Loki 日志",
        "query_prometheus": "查询 Prometheus 指标",
        "inspect_kubernetes": "检查 Kubernetes 状态与事件",
        "query_elasticsearch_logs": "查询 Elasticsearch 日志",
    }.get(name, name)


def _evidence_summary(name: str, count: int, data: Any) -> str:
    if isinstance(data, dict):
        samples = (
            data.get("samples")
            or data.get("entries")
            or data.get("series")
            or data.get("items")
            or data.get("values")
        )
        if samples:
            preview = json.dumps(samples[:2], ensure_ascii=False, default=str)[:1200]
            return redact(f"{_tool_description(name)}返回 {count} 条结果：{preview}")
        message = data.get("message") or data.get("summary")
        if message:
            return redact(f"{_tool_description(name)}：{message}")[:2000]
    return f"{_tool_description(name)}返回 {count} 条结果。"


def _extract_conclusion(content: str) -> str:
    text = content.strip()
    marker = "## 结论"
    if marker in text:
        text = text.split(marker, 1)[1]
    paragraphs = [value.strip() for value in text.split("\n\n") if value.strip()]
    conclusion = paragraphs[0] if paragraphs else "证据不足，尚不能确定根因"
    return conclusion.replace("**", "").replace("---", "").strip()[:2000]
