import asyncio
import math
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.query_catalog import TEMPLATES_BY_ID, templates_for_packs
from app.analysis.evidence import build_evidence
from app.config import Settings
from app.connectors.protocol import DatasourceGatewayProtocol
from app.llm.gateway import ModelGateway
from app.memory.context import fit_react_context
from app.memory.wiki import WikiMemory
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
from app.security.tenant import set_tenant_id


class AgentState(TypedDict, total=False):
    run_id: str
    incident: dict[str, Any]
    plan: dict[str, Any]
    tool_results: list[dict[str, Any]]
    collection_summary: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    report: dict[str, Any]
    memory: list[dict[str, Any]]
    used_packs: list[str]
    react_round: int
    react_action: dict[str, Any]


STEP_PROGRESS = {
    "normalize": 0.1,
    "plan": 0.25,
    "collect": 0.5,
    "compress": 0.62,
    "refine": 0.76,
    "analyze": 0.85,
    "validate": 0.94,
    "save": 1.0,
    "react": 0.25,
    "act": 0.52,
}


class RcaAgent:
    def __init__(
        self,
        settings: Settings,
        datasource_gateway: DatasourceGatewayProtocol,
        model_gateway: ModelGateway,
        events: EventBroker,
        memory: WikiMemory | None = None,
    ) -> None:
        self.settings = settings
        self.datasource_gateway = datasource_gateway
        self.model_gateway = model_gateway
        self.events = events
        self.memory = memory or WikiMemory(settings)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("normalize", self._normalize)
        builder.add_node("react", self._react)
        builder.add_node("act", self._act)
        builder.add_node("analyze", self._analyze)
        builder.add_node("validate", self._validate)
        builder.add_node("save", self._save)
        builder.add_edge(START, "normalize")
        builder.add_edge("normalize", "react")
        builder.add_conditional_edges(
            "react",
            self._route_react,
            {"act": "act", "analyze": "analyze"},
        )
        builder.add_edge("act", "react")
        builder.add_edge("analyze", "validate")
        builder.add_edge("validate", "save")
        builder.add_edge("save", END)
        return builder.compile()

    async def run(self, run_id: str) -> None:
        run = await AnalysisRun.get(id=run_id)
        incident = await Incident.get(id=run.incident_id)
        # Supervisor workers are long-lived tasks; set the workspace before every run.
        set_tenant_id(incident.tenant_id)
        latest_alert = (
            await AlertEvent.filter(incident_id=incident.id).order_by("-created_at").first()
        )
        initial_state: AgentState = {
            "run_id": run_id,
            "incident": {
                "id": incident.id,
                "title": incident.title,
                "alert_name": (
                    latest_alert.alert_name if latest_alert is not None else incident.title
                ),
                "service": incident.service,
                "cluster": incident.cluster,
                "namespace": incident.namespace,
                "instance": latest_alert.instance if latest_alert is not None else None,
                "severity": incident.severity,
                "source": latest_alert.source if latest_alert is not None else None,
                "labels": dict(latest_alert.labels) if latest_alert is not None else {},
                "annotations": (dict(latest_alert.annotations) if latest_alert is not None else {}),
                "alert_count": incident.alert_count,
                "is_test": self._is_test_alert(latest_alert),
                "started_at": incident.started_at.isoformat(),
                "ended_at": (
                    latest_alert.ended_at.isoformat()
                    if latest_alert is not None and latest_alert.ended_at
                    else None
                ),
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
        query = " ".join(
            str(state["incident"].get(key, ""))
            for key in ("title", "alert_name", "service", "cluster", "namespace", "annotations")
        )
        memory = [item.public_dict() for item in await self.memory.retrieve(query)]
        run = await AnalysisRun.get(id=run_id)
        saved_plan = dict(run.investigation_plan or {})
        used_packs = [
            str(value) for value in saved_plan.get("query_packs", []) if isinstance(value, str)
        ]
        iterations = saved_plan.get("iterations", [])
        react_round = len(iterations) if isinstance(iterations, list) else 0
        evidence = await self._load_evidence(run_id, state["incident"])
        executions = await ToolExecution.filter(analysis_run_id=run_id).all()
        collection_summary = _collection_summary(
            [
                {
                    "template_id": item.template_id,
                    "source": item.source,
                    "status": item.status,
                    "result_count": item.result_count,
                    "error_code": item.error_code,
                }
                for item in executions
            ]
        )
        await self._complete_step(run_id, "normalize")
        return {
            "incident": state["incident"],
            "memory": memory,
            "used_packs": used_packs,
            "react_round": react_round,
            "evidence": evidence,
            "collection_summary": collection_summary,
        }

    async def _react(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "react")
        used_packs = list(state.get("used_packs", []))
        react_round = int(state.get("react_round", 0))
        available = sorted(set(TEMPLATES_BY_ID[item].query_pack for item in TEMPLATES_BY_ID))
        if react_round >= self.settings.agent_max_react_rounds or len(used_packs) >= len(available):
            action = {
                "action": "finish",
                "query_pack": None,
                "rationale": "已达到 ReAct 调查轮次上限或查询包已用尽。",
            }
            token_usage = (0, 0)
        else:
            context = fit_react_context(
                incident=state["incident"],
                evidence=state.get("evidence", []),
                collection_summary=state.get("collection_summary", []),
                memories=state.get("memory", []),
                used_packs=used_packs,
                max_tokens=self.settings.agent_max_context_tokens,
            )
            result = await self.model_gateway.react(context, available_query_packs=available)
            action = result.value.model_dump(mode="json")
            token_usage = (result.input_tokens, result.output_tokens)
        run = await AnalysisRun.get(id=run_id)
        plan = dict(run.investigation_plan or {"mode": "react", "iterations": []})
        iterations = list(plan.get("iterations", []))
        iterations.append({"round": react_round + 1, **action})
        memory_refs = [
            {key: item.get(key) for key in ("document_id", "title", "heading", "score", "version")}
            for item in state.get("memory", [])
        ]
        plan.update(
            {
                "mode": "react",
                "iterations": iterations,
                "query_packs": used_packs,
                "retrieved_memory": memory_refs,
            }
        )
        run.investigation_plan = plan
        run.input_tokens += token_usage[0]
        run.output_tokens += token_usage[1]
        await run.save(update_fields=["investigation_plan", "input_tokens", "output_tokens"])
        await self.events.publish(run_id, "react.decision", iterations[-1])
        await self._complete_step(run_id, "react")
        return {"react_action": action, "react_round": react_round + 1}

    @staticmethod
    def _route_react(state: AgentState) -> str:
        return "act" if state.get("react_action", {}).get("action") == "query" else "analyze"

    async def _act(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "act")
        query_pack = str(state["react_action"].get("query_pack", ""))
        if not query_pack or query_pack in state.get("used_packs", []):
            raise ValueError("ReAct selected an empty or repeated query pack")
        results = await self._collect_query_packs(run_id, state["incident"], [query_pack])
        await self._store_evidence(run_id, state["incident"], results)
        evidence = await self._load_evidence(run_id, state["incident"])
        memory_query = " ".join(
            [
                str(state["incident"].get("title", "")),
                str(state["incident"].get("service", "")),
                *[str(item.get("summary", ""))[:800] for item in evidence[:8]],
            ]
        )
        refreshed_memory = [item.public_dict() for item in await self.memory.retrieve(memory_query)]
        used_packs = [*state.get("used_packs", []), query_pack]
        collection_summary = [
            *state.get("collection_summary", []),
            *_collection_summary(results),
        ]
        run = await AnalysisRun.get(id=run_id)
        plan = dict(run.investigation_plan or {})
        plan["query_packs"] = used_packs
        run.investigation_plan = plan
        await run.save(update_fields=["investigation_plan"])
        await self._complete_step(run_id, "act")
        return {
            "tool_results": results,
            "evidence": evidence,
            "used_packs": used_packs,
            "collection_summary": collection_summary,
            "memory": refreshed_memory,
        }

    async def _plan(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "plan")
        run = await AnalysisRun.get(id=run_id)
        if run.investigation_plan:
            plan = dict(run.investigation_plan)
        else:
            result = await self.model_gateway.plan(state["incident"])
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
        results = await self._collect_query_packs(
            run_id,
            state["incident"],
            list(state["plan"]["query_packs"]),
        )
        await self._complete_step(run_id, "collect")
        return {"tool_results": results}

    async def _collect_query_packs(
        self,
        run_id: str,
        incident: dict[str, Any],
        query_packs: list[str],
    ) -> list[dict[str, Any]]:
        start, end = _investigation_window(incident)
        templates = templates_for_packs(query_packs)
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
        return list(results)

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
        result = await self.datasource_gateway.execute(
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

    async def _store_evidence(
        self,
        run_id: str,
        incident: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> None:
        represented_tool_ids = {
            item
            for item in await EvidenceItem.filter(analysis_run_id=run_id).values_list(
                "tool_execution_id",
                flat=True,
            )
            if item
        }
        for raw in tool_results:
            tool_execution_id = str(raw["tool_execution_id"])
            if tool_execution_id in represented_tool_ids:
                continue
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
                service=str(incident["service"]),
                tool_execution_id=tool_execution_id,
            )
            if record is None:
                continue
            if await EvidenceItem.get_or_none(
                analysis_run_id=run_id,
                content_hash=record.content_hash,
            ):
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
            represented_tool_ids.add(tool_execution_id)
            await self.events.publish(
                run_id,
                "evidence.created",
                {"evidence_id": item.id, "type": item.type},
            )

    async def _load_evidence(
        self,
        run_id: str,
        incident: dict[str, Any],
    ) -> list[dict[str, Any]]:
        evidence = [
            _evidence_to_dict(item)
            for item in await EvidenceItem.filter(analysis_run_id=run_id).all()
        ]
        evidence.sort(
            key=lambda item: _evidence_relevance(item, str(incident["started_at"])),
            reverse=True,
        )
        return evidence[: self.settings.max_evidence_items]

    async def _compress(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "compress")
        await self._store_evidence(
            run_id,
            state["incident"],
            state.get("tool_results", []),
        )
        evidence = await self._load_evidence(run_id, state["incident"])
        collection_summary = _collection_summary(state.get("tool_results", []))
        await self._complete_step(run_id, "compress")
        return {"evidence": evidence, "collection_summary": collection_summary}

    async def _refine(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "refine")
        used_packs = list(state["plan"]["query_packs"])
        result = await self.model_gateway.refine(
            state["incident"],
            state.get("evidence", []),
            used_packs,
            state.get("collection_summary", []),
        )
        additional_packs = [
            pack for pack in dict.fromkeys(result.value.query_packs) if pack not in used_packs
        ]
        run = await AnalysisRun.get(id=run_id)
        run.input_tokens += result.input_tokens
        run.output_tokens += result.output_tokens
        plan = dict(state["plan"])
        evidence = state.get("evidence", [])
        collection_summary = state.get("collection_summary", [])
        if additional_packs:
            plan = {"query_packs": used_packs + additional_packs}
            run.investigation_plan = plan
            extra_results = await self._collect_query_packs(
                run_id,
                state["incident"],
                additional_packs,
            )
            await self._store_evidence(run_id, state["incident"], extra_results)
            evidence = await self._load_evidence(run_id, state["incident"])
            collection_summary = collection_summary + _collection_summary(extra_results)
        await run.save(
            update_fields=["investigation_plan", "input_tokens", "output_tokens"]
            if additional_packs
            else ["input_tokens", "output_tokens"]
        )
        await self._complete_step(run_id, "refine")
        return {
            "plan": plan,
            "evidence": evidence,
            "collection_summary": collection_summary,
        }

    async def _analyze(self, state: AgentState) -> AgentState:
        run_id = state["run_id"]
        await self._mark(run_id, "analyze")
        existing = await RootCauseReport.get_or_none(analysis_run_id=run_id)
        if existing is not None:
            report = _report_to_output(existing).model_dump(mode="json")
        else:
            context = fit_react_context(
                incident=state["incident"],
                evidence=state.get("evidence", []),
                collection_summary=state.get("collection_summary", []),
                memories=state.get("memory", []),
                used_packs=state.get("used_packs", []),
                max_tokens=self.settings.agent_max_context_tokens,
            )
            result = await self.model_gateway.analyze(
                context["incident"],
                context["evidence"],
                collection_summary=context["collection_summary"],
                memory=context["retrieved_memory"],
            )
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
            context = fit_react_context(
                incident=state["incident"],
                evidence=state.get("evidence", []),
                collection_summary=state.get("collection_summary", []),
                memories=state.get("memory", []),
                used_packs=state.get("used_packs", []),
                max_tokens=self.settings.agent_max_context_tokens,
            )
            result = await self.model_gateway.analyze(
                context["incident"],
                context["evidence"],
                collection_summary=context["collection_summary"],
                memory=context["retrieved_memory"],
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
        report = _calibrate_confidence(report, state.get("evidence", []))
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


def _collection_summary(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "template_id": str(item.get("template_id", "")),
            "source": str(item.get("source", "")),
            "status": str(item.get("status", "")),
            "result_count": int(item.get("result_count", 0)),
            "error_code": item.get("error_code"),
        }
        for item in tool_results
    ]


def _calibrate_confidence(
    report: RootCauseOutput,
    evidence: list[dict[str, Any]],
) -> RootCauseOutput:
    if not evidence:
        ceiling = 0.2
    else:
        sources = {str(item.get("source", "")) for item in evidence if item.get("source")}
        ceiling = 0.65
        if len(evidence) >= 2:
            ceiling += 0.1
        if len(evidence) >= 5:
            ceiling += 0.05
        if len(sources) >= 2:
            ceiling += 0.08
        if len(sources) >= 3:
            ceiling += 0.05
        ceiling = min(ceiling, 0.93)

    for hypothesis in report.hypotheses:
        hypothesis_ceiling = ceiling
        if len(hypothesis.supporting_evidence_ids) == 1:
            hypothesis_ceiling = min(hypothesis_ceiling, 0.72)
        hypothesis.confidence = min(hypothesis.confidence, hypothesis_ceiling)
    if report.hypotheses:
        report.confidence = min(
            report.confidence,
            ceiling,
            max(item.confidence for item in report.hypotheses),
        )
    else:
        report.confidence = min(report.confidence, 0.2)

    source_count = len({str(item.get("source", "")) for item in evidence if item.get("source")})
    boundary = "缺少跨数据源交叉验证"
    if report.hypotheses and source_count < 2 and boundary not in report.missing_evidence:
        report.missing_evidence.append(boundary)
    return report


def _investigation_window(incident: dict[str, Any]) -> tuple[datetime, datetime]:
    started_at = _parse_datetime(str(incident["started_at"]))
    ended_at = _parse_datetime(str(incident["ended_at"])) if incident.get("ended_at") else _utcnow()
    start = started_at - timedelta(minutes=60)
    minimum_end = started_at + timedelta(minutes=30)
    maximum_end = started_at + timedelta(hours=6)
    end = max(minimum_end, min(ended_at, maximum_end))
    return start, end


def _evidence_relevance(item: dict[str, Any], incident_started_at: str) -> float:
    score = float(item["quality"])
    values = item.get("values", {})
    if isinstance(values, dict):
        change = values.get("change_percent")
        if isinstance(change, int | float):
            score += min(abs(float(change)) / 100, 1) * 0.2
        count = values.get("count")
        if isinstance(count, int | float) and count > 0:
            score += min(math.log1p(float(count)) / 50, 0.1)
    if item.get("observed_at"):
        observed_at = _parse_datetime(str(item["observed_at"]))
        started_at = _parse_datetime(incident_started_at)
        distance = abs((observed_at - started_at).total_seconds())
        if distance <= 15 * 60:
            score += 0.2
        elif distance <= 60 * 60:
            score += 0.12
        elif distance <= 6 * 60 * 60:
            score += 0.05
    return score


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)
