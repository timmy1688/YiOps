from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents.domain import ToolResult
from app.connectors.client import DatasourceClient
from app.models import AnalysisRun, EvidenceItem, Incident, RootCauseReport

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_incident_analysis",
            "description": (
                "读取指定 YiOps 故障的最新分析状态、根因报告和证据。"
                "当用户要求深入分析、解释或比较某个故障时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "故障 ID，可从上下文 recent_incidents 获取",
                    }
                },
                "required": ["incident_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_loki_logs",
            "description": (
                "查询 Loki 日志。用户要求查看、搜索、统计 Loki 日志时必须调用。"
                "这是只读查询，返回真实日志及标签。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "LogQL 日志查询，必须以流选择器开头。例如查询所有 namespace："
                            "{namespace=~\".+\"}；按服务：{service=\"api\"}"
                        ),
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "向前查询多少分钟，默认 30，范围 1-1440",
                        "minimum": 1,
                        "maximum": 1440,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少条，默认 10，范围 1-50",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus",
            "description": "执行只读 PromQL 区间查询，返回真实时间序列。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "PromQL 表达式"},
                    "minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1440,
                        "description": "向前查询多少分钟，默认 30",
                    },
                    "step_seconds": {
                        "type": "integer",
                        "minimum": 15,
                        "maximum": 300,
                        "description": "采样步长秒数，默认 30",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_kubernetes",
            "description": "只读检查 Kubernetes 的异常对象或 Warning Event。",
            "parameters": {
                "type": "object",
                "properties": {
                    "inspection": {
                        "type": "string",
                        "enum": [
                            "abnormal_pods",
                            "unhealthy_workloads",
                            "unhealthy_nodes",
                            "warning_events",
                        ],
                    },
                    "cluster": {"type": "string", "description": "可选集群 ID"},
                    "namespace": {"type": "string", "description": "可选 namespace"},
                    "minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1440,
                        "description": "Warning Event 查询时间范围，默认 60 分钟",
                    },
                },
                "required": ["inspection"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_elasticsearch_logs",
            "description": "在 Elasticsearch 日志索引中执行只读搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "simple_query_string 搜索条件，默认 *",
                    },
                    "service": {"type": "string", "description": "可选服务名"},
                    "minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1440,
                        "description": "向前查询多少分钟，默认 30",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "description": "最多返回多少条，默认 10",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
]


class ChatToolRunner:
    def __init__(self, datasource_client: DatasourceClient) -> None:
        self.datasource_client = datasource_client

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        end = datetime.now(UTC)
        minutes = self._bounded_int(arguments.get("minutes"), default=30, low=1, high=1440)
        start = end - timedelta(minutes=minutes)
        if name == "get_incident_analysis":
            return await self._incident_analysis(str(arguments.get("incident_id", "")))
        if name == "query_loki_logs":
            result = await self.datasource_client.query_loki_logs(
                query=str(arguments.get("query", "")),
                start=start,
                end=end,
                limit=self._bounded_int(arguments.get("limit"), default=10, low=1, high=50),
            )
        elif name == "query_prometheus":
            result = await self.datasource_client.query_prometheus_range(
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
        elif name == "inspect_kubernetes":
            result = await self.datasource_client.inspect_kubernetes(
                inspection=str(arguments.get("inspection", "")),
                cluster=self._optional_string(arguments.get("cluster")),
                namespace=self._optional_string(arguments.get("namespace")),
                start=start,
                end=end,
            )
        elif name == "query_elasticsearch_logs":
            result = await self.datasource_client.query_elasticsearch_logs(
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
        incident = await Incident.get_or_none(id=incident_id)
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
            evidence = await EvidenceItem.filter(analysis_run_id=run.id).order_by(
                "-quality"
            ).limit(20)
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
