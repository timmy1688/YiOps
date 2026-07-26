import asyncio
from dataclasses import asdict
from datetime import timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.analysis.evidence import build_evidence
from app.config import Settings
from app.connectors.client import DatasourceClient
from app.llm.deepseek import DeepSeekClient
from app.models import (
    AlertEvent,
    AnalysisRun,
    EvidenceItem,
    Incident,
    RootCauseReport,
    ToolExecution,
    new_id,
)
from app.runtime.events import EventBroker
from app.schemas import RootCauseOutput
from app.tools.catalog import TEMPLATES_BY_ID, templates_for_packs


class AgentState(TypedDict, total=False):
    run_id: str
    incident: dict[str, Any]
    plan: dict[str, Any]
    tool_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    report: dict[str, Any]


STEP_PROGRESS = {
    "normalize": 0.1,
    "plan": 0.25,
    "collect": 0.5,
    "compress": 0.68,
    "analyze": 0.85,
    "validate": 0.94,
    "save": 1.0,
}


class AnalysisAgent:
    def __init__(
        self,
        settings: Settings,
        datasource_client: DatasourceClient,
        llm: DeepSeekClient,
        events: EventBroker,
    ) -> None:
        self.settings = settings
        self.datasource_client = datasource_client
        self.llm = llm
        self.events = events
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("normalize", self._normalize)
        builder.add_node("plan", self._plan)
        builder.add_node("collect", self._collect)
        builder.add_node("compress", self._compress)
        builder.add_node("analyze", self._analyze)
        builder.add_node("validate", self._validate)
        builder.add_node("save", self._save)
        builder.add_edge(START, "normalize")
        builder.add_edge("normalize", "plan")
        builder.add_edge("plan", "collect")
        builder.add_edge("collect", "compress")
        builder.add_edge("compress", "analyze")
        builder.add_edge("analyze", "validate")
        builder.add_edge("validate", "save")
        builder.add_edge("save", END)
        return builder.compile()

    async def run(self, run_id: str) -> None:
        run = await AnalysisRun.get(id=run_id)
        incident = await Incident.get(id=run.incident_id)
        latest_alert = (
            await AlertEvent.filter(incident_id=incident.id).order_by("-created_at").first()
        )
        initial_state: AgentState = {
            "run_id": run_id,
            "incident": {
                "id": incident.id,
                "title": incident.title,
                "alert_name": incident.title,
                "service": incident.service,
                "cluster": incident.cluster,
                "namespace": incident.namespace,
                "severity": incident.severity,
                "is_test": self._is_test_alert(latest_alert),
                "started_at": incident.started_at.isoformat(),
            },
        }
        await self.graph.ainvoke(initial_state)

    @staticmethod
    def _is_test_alert(alert: AlertEvent | None) -> bool:
        if alert is None:
            return False
        marker = str(alert.labels.get("yiops_test", "")).lower()
        if marker in {"1", "true", "yes"}:
            return True
        content = str(alert.labels) + str(alert.annotations)
        return any(keyword in content.lower() for keyword in ("测试", "验证", "演示"))

    async def fail(self, run_id: str, exc: Exception) -> None:
        await AnalysisRun.filter(id=run_id).update(
            status="failed_final",
            error_code=type(exc).__name__,
            error_message=str(exc)[:2000],
        )
        await self.events.publish(
            run_id,
            "run.failed",
            {"error_code": type(exc).__name__, "message": str(exc)[:500]},
        )

    async def _mark(self, run_id: str, step: str) -> None:
        run = await AnalysisRun.get(id=run_id)
        run.status = "running"
        run.current_step = step
        run.progress = STEP_PROGRESS[step]
        run.error_code = None
        run.error_message = None
        update_fields = ["status", "current_step", "progress", "error_code", "error_message"]
        if run.started_at is None:
            run.started_at = _utcnow()
            update_fields.append("started_at")
        await run.save(update_fields=update_fields)
        await self.events.publish(
            run_id,
            "node.started",
            {"node": step, "progress": STEP_PROGRESS[step]},
        )

    async def _complete_step(self, run_id: str, step: str) -> None:
        await self.events.publish(
            run_id,
            "node.completed",
            {"node": step, "progress": STEP_PROGRESS[step]},
        )

    async def _normalize(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "normalize")
        await self._complete_step(run_id, "normalize")
        return {"incident": state["incident"]}

    async def _plan(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "plan")
        run = await AnalysisRun.get(id=run_id)
        if run.investigation_plan:
            plan = dict(run.investigation_plan)
        else:
            result = await self.llm.plan(state["incident"])
            packs = list(dict.fromkeys(result.value.query_packs))
            plan = {"query_packs": packs}
            run.investigation_plan = plan
            run.input_tokens += result.input_tokens
            run.output_tokens += result.output_tokens
            await run.save(update_fields=["investigation_plan", "input_tokens", "output_tokens"])
        await self._complete_step(run_id, "plan")
        return {"plan": plan}

    async def _collect(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "collect")
        incident = state["incident"]
        started_at = _parse_datetime(str(incident["started_at"]))
        start = started_at - timedelta(minutes=60)
        end = started_at + timedelta(minutes=30)
        templates = templates_for_packs(list(state["plan"]["query_packs"]))
        results = await asyncio.gather(
            *[
                self._execute_template(
                    run_id,
                    template.id,
                    service=str(incident["service"]),
                    cluster=(str(incident["cluster"]) if incident.get("cluster") else None),
                    namespace=(str(incident["namespace"]) if incident.get("namespace") else None),
                    start=start,
                    end=end,
                )
                for template in templates
            ]
        )
        await self._complete_step(run_id, "collect")
        return {"tool_results": results}

    async def _execute_template(
        self,
        run_id: str,
        template_id: str,
        *,
        service: str,
        cluster: str | None,
        namespace: str | None,
        start,
        end,
    ) -> dict[str, Any]:
        existing = await ToolExecution.get_or_none(
            analysis_run_id=run_id,
            template_id=template_id,
        )
        if existing is not None:
            return {
                "tool_execution_id": existing.id,
                "source": existing.source,
                "query_pack": existing.query_pack,
                "template_id": existing.template_id,
                "status": existing.status,
                "result_count": existing.result_count,
                "data": existing.result_summary or {},
                "duration_ms": existing.duration_ms,
                "error_code": existing.error_code,
            }
        template = TEMPLATES_BY_ID[template_id]
        await self.events.publish(
            run_id,
            "tool.started",
            {"template_id": template.id, "source": template.source},
        )
        result = await self.datasource_client.execute(
            template,
            service=service,
            cluster=cluster,
            namespace=namespace,
            start=start,
            end=end,
        )
        execution = await ToolExecution.create(
            id=new_id("tool"),
            analysis_run_id=run_id,
            source=result.source,
            query_pack=result.query_pack,
            template_id=result.template_id,
            parameters={
                "service": service,
                "cluster": cluster,
                "namespace": namespace,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            status=result.status,
            duration_ms=result.duration_ms,
            result_count=result.result_count,
            result_summary=result.data,
            error_code=result.error_code,
        )
        await self.events.publish(
            run_id,
            "tool.completed",
            {
                "tool_execution_id": execution.id,
                "template_id": template.id,
                "source": template.source,
                "status": result.status,
            },
        )
        return {"tool_execution_id": execution.id, **asdict(result)}

    async def _compress(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "compress")
        existing = await EvidenceItem.filter(analysis_run_id=run_id).all()
        if existing:
            evidence = [_evidence_to_dict(item) for item in existing]
        else:
            evidence = []
            for raw in state.get("tool_results", []):
                template = TEMPLATES_BY_ID[str(raw["template_id"])]
                from app.agents.domain import ToolResult

                result = ToolResult(
                    source=raw["source"],
                    query_pack=str(raw["query_pack"]),
                    template_id=str(raw["template_id"]),
                    status=str(raw["status"]),
                    result_count=int(raw.get("result_count", 0)),
                    data=dict(raw.get("data", {})),
                    duration_ms=int(raw.get("duration_ms", 0)),
                    error_code=raw.get("error_code"),
                )
                record = build_evidence(
                    result,
                    template,
                    service=str(state["incident"]["service"]),
                    tool_execution_id=str(raw["tool_execution_id"]),
                )
                if record is None:
                    continue
                item = await EvidenceItem.create(
                    id=record.id,
                    analysis_run_id=run_id,
                    tool_execution_id=record.tool_execution_id,
                    type=record.type,
                    source=record.source,
                    title=record.title,
                    summary=record.summary,
                    observed_at=record.observed_at,
                    subject=record.subject,
                    values=record.values,
                    quality=record.quality,
                    content_hash=record.content_hash,
                )
                evidence.append(_evidence_to_dict(item))
                await self.events.publish(
                    run_id,
                    "evidence.created",
                    {"evidence_id": item.id, "type": item.type},
                )
        evidence.sort(key=lambda item: float(item["quality"]), reverse=True)
        evidence = evidence[: self.settings.max_evidence_items]
        await self._complete_step(run_id, "compress")
        return {"evidence": evidence}

    async def _analyze(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "analyze")
        existing = await RootCauseReport.get_or_none(analysis_run_id=run_id)
        if existing is not None:
            report = _report_to_output(existing).model_dump(mode="json")
        else:
            result = await self.llm.analyze(state["incident"], state.get("evidence", []))
            report = result.value.model_dump(mode="json")
            run = await AnalysisRun.get(id=run_id)
            run.input_tokens += result.input_tokens
            run.output_tokens += result.output_tokens
            await run.save(update_fields=["input_tokens", "output_tokens"])
        await self._complete_step(run_id, "analyze")
        return {"report": report}

    async def _validate(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "validate")
        report = RootCauseOutput.model_validate(state["report"])
        error = _report_validation_error(report, state.get("evidence", []))
        if error:
            result = await self.llm.analyze(
                state["incident"],
                state.get("evidence", []),
                validation_error=error,
            )
            report = result.value
            error = _report_validation_error(report, state.get("evidence", []))
            run = await AnalysisRun.get(id=run_id)
            run.input_tokens += result.input_tokens
            run.output_tokens += result.output_tokens
            await run.save(update_fields=["input_tokens", "output_tokens"])
        if error:
            raise ValueError(f"REPORT_VALIDATION_FAILED: {error}")
        await self._complete_step(run_id, "validate")
        return {"report": report.model_dump(mode="json")}

    async def _save(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "save")
        report = RootCauseOutput.model_validate(state["report"])
        status = "completed" if report.hypotheses else "insufficient_evidence"
        stored = await RootCauseReport.get_or_none(analysis_run_id=run_id)
        if stored is None:
            stored = await RootCauseReport.create(
                id=new_id("report"),
                analysis_run_id=run_id,
                status=status,
                summary=report.summary,
                confidence=report.confidence,
                hypotheses=[hypothesis.model_dump(mode="json") for hypothesis in report.hypotheses],
                recommended_actions=report.recommended_actions,
                missing_evidence=report.missing_evidence,
            )
        await AnalysisRun.filter(id=run_id).update(
            status=status,
            current_step="save",
            progress=1.0,
            completed_at=_utcnow(),
        )
        await self._complete_step(run_id, "save")
        await self.events.publish(
            run_id,
            "report.completed",
            {"report_id": stored.id, "status": status},
        )
        return {"report": report.model_dump(mode="json")}


def _evidence_to_dict(item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "source": item.source,
        "title": item.title,
        "summary": item.summary,
        "observed_at": item.observed_at.isoformat() if item.observed_at else None,
        "subject": item.subject,
        "values": item.values,
        "quality": item.quality,
    }


def _report_to_output(report: RootCauseReport) -> RootCauseOutput:
    return RootCauseOutput(
        summary=report.summary,
        confidence=report.confidence,
        hypotheses=report.hypotheses,
        recommended_actions=report.recommended_actions,
        missing_evidence=report.missing_evidence,
    )


def _report_validation_error(
    report: RootCauseOutput,
    evidence: list[dict[str, Any]],
) -> str | None:
    valid_ids = {str(item["id"]) for item in evidence}
    invalid: set[str] = set()
    for hypothesis in report.hypotheses:
        invalid.update(set(hypothesis.supporting_evidence_ids) - valid_ids)
        invalid.update(set(hypothesis.contradicting_evidence_ids) - valid_ids)
    if invalid:
        return f"Unknown evidence IDs: {sorted(invalid)}"
    if report.hypotheses and not any(
        hypothesis.supporting_evidence_ids for hypothesis in report.hypotheses
    ):
        return "Every hypothesis must cite at least one supporting evidence ID"
    return None


def _parse_datetime(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utcnow():
    from datetime import UTC, datetime

    return datetime.now(UTC)
