from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.domain import ToolResult
from app.connectors.protocol import DatasourceGatewayProtocol
from app.models import AnalysisRun, EvidenceItem, Incident, RootCauseReport
from app.security.tenant import tenant_filter


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentAnalysisArguments(ToolArguments):
    incident_id: str = Field(description="故障 ID，可从上下文 recent_incidents 获取")


class LokiQueryArguments(ToolArguments):
    query: str = Field(
        description=('LogQL 查询，必须以流选择器开头，例如 {namespace=~".+"} 或 {service="api"}')
    )
    minutes: int = Field(default=30, ge=1, le=1440, description="向前查询分钟数")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回日志条数")


class PrometheusQueryArguments(ToolArguments):
    query: str = Field(description="PromQL 表达式")
    minutes: int = Field(default=30, ge=1, le=1440, description="向前查询分钟数")
    step_seconds: int = Field(default=30, ge=15, le=300, description="采样步长秒数")


class TempoSearchArguments(ToolArguments):
    query: str = Field(
        description='TraceQL 查询，例如 { resource.service.name = "api" && status = error }'
    )
    minutes: int = Field(default=30, ge=1, le=1440, description="向前查询分钟数")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回 Trace 数")


class TempoTraceArguments(ToolArguments):
    trace_id: str = Field(description="16-32 位十六进制 Tempo Trace ID")
    minutes: int = Field(default=30, ge=1, le=1440, description="限定查询时间范围")


class KubernetesInspectionArguments(ToolArguments):
    inspection: Literal[
        "abnormal_pods",
        "unhealthy_workloads",
        "unhealthy_nodes",
        "warning_events",
    ]
    cluster: str | None = Field(default=None, description="可选集群 ID")
    namespace: str | None = Field(default=None, description="可选 Namespace")
    minutes: int = Field(default=60, ge=1, le=1440, description="Event 查询时间范围")


class ElasticsearchQueryArguments(ToolArguments):
    query: str = Field(default="*", description="simple_query_string 搜索条件")
    service: str | None = Field(default=None, description="可选服务名")
    minutes: int = Field(default=30, ge=1, le=1440, description="向前查询分钟数")
    limit: int = Field(default=10, ge=1, le=50, description="最多返回日志条数")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    arguments: type[BaseModel]
    datasource: str | None = None


TOOL_SPECS = (
    ToolSpec(
        "get_incident_analysis",
        "读取指定 YiOps 故障的最新分析状态、根因报告和证据。",
        IncidentAnalysisArguments,
    ),
    ToolSpec(
        "query_loki_logs",
        "查询真实 Loki 日志及标签；用户要求查看、搜索或统计日志时调用。",
        LokiQueryArguments,
        "loki",
    ),
    ToolSpec(
        "query_prometheus",
        "执行只读 PromQL 区间查询并返回真实时间序列。",
        PrometheusQueryArguments,
        "prometheus",
    ),
    ToolSpec(
        "search_tempo_traces",
        "使用 TraceQL 搜索错误链路、慢链路或服务调用链。",
        TempoSearchArguments,
        "tempo",
    ),
    ToolSpec(
        "get_tempo_trace",
        "根据 Trace ID 读取完整 Span，用于分析调用路径、错误和耗时。",
        TempoTraceArguments,
        "tempo",
    ),
    ToolSpec(
        "inspect_kubernetes",
        "只读检查 Kubernetes 异常对象或 Warning Event。",
        KubernetesInspectionArguments,
        "kubernetes",
    ),
    ToolSpec(
        "query_elasticsearch_logs",
        "在 Elasticsearch 日志索引中执行只读搜索。",
        ElasticsearchQueryArguments,
        "elasticsearch",
    ),
)


def available_tool_specs(context: dict[str, object]) -> list[ToolSpec]:
    """Return only tools backed by enabled datasources in this workspace."""
    configured = context.get("available_datasources")
    if not isinstance(configured, list):
        return list(TOOL_SPECS)
    sources = {
        str(item.get("type")) for item in configured if isinstance(item, dict) and item.get("type")
    }
    return [spec for spec in TOOL_SPECS if spec.datasource is None or spec.datasource in sources]


class DatasourceToolExecutor:
    def __init__(
        self,
        datasource_gateway: DatasourceGatewayProtocol,
        context: dict[str, object] | None = None,
    ) -> None:
        self.datasource_gateway = datasource_gateway
        incident = (context or {}).get("incident")
        self.defaults = incident if isinstance(incident, dict) else {}

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        end = datetime.now(UTC)
        minutes = self._bounded_int(arguments.get("minutes"), default=30, low=1, high=1440)
        start = end - timedelta(minutes=minutes)
        if name == "get_incident_analysis":
            return await self._incident_analysis(str(arguments.get("incident_id", "")))
        if name == "query_loki_logs":
            result = await self.datasource_gateway.query_loki_logs(
                query=str(arguments.get("query", "")),
                start=start,
                end=end,
                limit=self._bounded_int(arguments.get("limit"), default=10, low=1, high=50),
            )
        elif name == "query_prometheus":
            result = await self.datasource_gateway.query_prometheus_range(
                query=str(arguments.get("query", "")),
                start=start,
                end=end,
                step_seconds=self._bounded_int(
                    arguments.get("step_seconds"),
                    default=30,
                    low=15,
                    high=300,
                ),
            )
        elif name == "search_tempo_traces":
            result = await self.datasource_gateway.search_tempo_traces(
                query=str(arguments.get("query", "")),
                start=start,
                end=end,
                limit=self._bounded_int(arguments.get("limit"), default=10, low=1, high=50),
            )
        elif name == "get_tempo_trace":
            result = await self.datasource_gateway.get_tempo_trace(
                trace_id=str(arguments.get("trace_id", "")),
                start=start,
                end=end,
            )
        elif name == "inspect_kubernetes":
            result = await self.datasource_gateway.inspect_kubernetes(
                inspection=str(arguments.get("inspection", "")),
                cluster=self._optional_string(arguments.get("cluster"))
                or self._optional_string(self.defaults.get("cluster")),
                namespace=self._optional_string(arguments.get("namespace"))
                or self._optional_string(self.defaults.get("namespace")),
                start=start,
                end=end,
            )
        elif name == "query_elasticsearch_logs":
            result = await self.datasource_gateway.query_elasticsearch_logs(
                query=str(arguments.get("query", "*")),
                service=self._optional_string(arguments.get("service")),
                start=start,
                end=end,
                limit=self._bounded_int(arguments.get("limit"), default=10, low=1, high=50),
            )
        else:
            raise ValueError(f"不允许调用工具：{name}")
        return self._result(name, arguments, start, end, result)

    @staticmethod
    async def _incident_analysis(incident_id: str) -> dict[str, Any]:
        incident = await Incident.get_or_none(id=incident_id, **tenant_filter())
        if incident is None:
            raise ValueError("未找到指定故障")
        run = await AnalysisRun.filter(incident_id=incident.id).order_by("-created_at").first()
        data: dict[str, Any] = {
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
            }
        }
        evidence_count = 0
        if run:
            data["analysis"] = {
                "status": run.status,
                "current_step": run.current_step,
                "progress": run.progress,
                "model_name": run.model_name,
                "error_message": run.error_message,
            }
            evidence = (
                await EvidenceItem.filter(analysis_run_id=run.id).order_by("-quality").limit(20)
            )
            evidence_count = len(evidence)
            data["evidence"] = [
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
            report = await RootCauseReport.get_or_none(analysis_run_id=run.id)
            if report:
                data["report"] = {
                    "status": report.status,
                    "summary": report.summary,
                    "confidence": report.confidence,
                    "hypotheses": report.hypotheses,
                    "recommended_actions": report.recommended_actions,
                    "missing_evidence": report.missing_evidence,
                }
        return {
            "name": "get_incident_analysis",
            "status": "completed",
            "result_count": evidence_count,
            "duration_ms": 0,
            "parameters": {"incident_id": incident_id},
            "error_code": None,
            "data": data,
        }

    @staticmethod
    def _result(
        name: str,
        arguments: dict[str, Any],
        start: datetime,
        end: datetime,
        result: ToolResult,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "status": result.status,
            "result_count": result.result_count,
            "duration_ms": result.duration_ms,
            "parameters": {
                **arguments,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "error_code": result.error_code,
            "data": result.data,
        }

    @staticmethod
    def _bounded_int(value: object, *, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value) if value is not None else default
        except (TypeError, ValueError):
            parsed = default
        return min(max(parsed, low), high)

    @staticmethod
    def _optional_string(value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None
