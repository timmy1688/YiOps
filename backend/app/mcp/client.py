from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast

import httpx2
from mcp import Client
from mcp.client._transport import TransportStreams
from mcp.client.streamable_http import streamable_http_client

from app.agents.domain import QueryTemplate, ToolResult
from app.config import Settings
from app.models import DatasourceConfig
from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id


class MCPDatasourceGateway:
    """API-side gateway. All real datasource access crosses the YiOps MCP boundary."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(
        self,
        template: QueryTemplate,
        *,
        service: str,
        start: datetime,
        end: datetime,
        cluster: str | None = None,
        namespace: str | None = None,
    ) -> ToolResult:
        started = monotonic()
        try:
            result = await self._execute(
                template,
                service=service,
                start=start,
                end=end,
                cluster=cluster,
                namespace=namespace,
            )
            result.duration_ms = int((monotonic() - started) * 1000)
            return result
        except Exception as exc:  # MCP transport/protocol failures are reported as evidence gaps.
            return ToolResult(
                source=template.source,
                query_pack=template.query_pack,
                template_id=template.id,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_code=type(exc).__name__,
                data={"message": str(exc)[:500]},
            )

    async def _execute(
        self,
        template: QueryTemplate,
        *,
        service: str,
        start: datetime,
        end: datetime,
        cluster: str | None = None,
        namespace: str | None = None,
    ) -> ToolResult:
        if template.source == "prometheus":
            query = template.query.replace("{service}", service.replace('"', ""))
            raw = await self.query_prometheus_range(
                query=query, start=start, end=end, step_seconds=30
            )
            values = [
                float(point[1])
                for series in raw.data.get("series", [])
                if isinstance(series, dict)
                for point in series.get("values", [])
                if isinstance(point, list) and len(point) == 2 and self._is_number(point[1])
            ]
            return replace(
                raw,
                query_pack=template.query_pack,
                template_id=template.id,
                result_count=len(values),
                data={"values": values[-600:]},
            )
        if template.source == "loki":
            escaped_namespace = (
                namespace.replace("\\", "\\\\").replace('"', '\\"') if namespace else None
            )
            selector = (
                f'namespace="{escaped_namespace}"' if escaped_namespace else 'namespace=~".+"'
            )
            query = template.query.replace("{service}", service.replace('"', "")).replace(
                'namespace=~"{namespace}"', selector
            )
            raw = await self.query_loki_logs(
                query=query,
                start=start,
                end=end,
                limit=self.settings.max_log_samples,
            )
            samples = [
                str(item.get("line", ""))[:1000]
                for item in raw.data.get("entries", [])
                if isinstance(item, dict)
            ]
            return replace(
                raw,
                query_pack=template.query_pack,
                template_id=template.id,
                result_count=len(samples),
                data={"samples": samples},
            )
        if template.source == "tempo":
            escaped_service = service.replace("\\", "\\\\").replace('"', '\\"')
            raw = await self.search_tempo_traces(
                query=template.query.replace("{service}", escaped_service),
                start=start,
                end=end,
                limit=20,
            )
            return replace(raw, query_pack=template.query_pack, template_id=template.id)
        if template.source == "kubernetes":
            inspection = {
                "k8s_api_abnormal_pods": "abnormal_pods",
                "k8s_api_workload_status": "unhealthy_workloads",
                "k8s_api_node_conditions": "unhealthy_nodes",
                "k8s_api_warning_events": "warning_events",
            }.get(template.id)
            if inspection is None:
                raise ValueError(f"Unsupported Kubernetes template: {template.id}")
            raw = await self.inspect_kubernetes(
                inspection=inspection,
                cluster=cluster,
                namespace=namespace,
                start=start,
                end=end,
            )
            return replace(raw, query_pack=template.query_pack, template_id=template.id)
        raw = await self.query_elasticsearch_logs(
            query="log.level:(ERROR OR FATAL) OR message:*Exception*",
            service=service,
            start=start,
            end=end,
            limit=self.settings.max_log_samples,
        )
        samples = [
            str(item.get("message", ""))[:1000]
            for item in raw.data.get("entries", [])
            if isinstance(item, dict)
        ]
        return replace(
            raw,
            query_pack=template.query_pack,
            template_id=template.id,
            result_count=len(samples),
            data={"samples": samples},
        )

    async def query_loki_logs(
        self, *, query: str, start: datetime, end: datetime, limit: int
    ) -> ToolResult:
        return self._tool_result(
            await self._call(
                "query_loki_logs",
                {
                    "query": query,
                    "start": self._time(start),
                    "end": self._time(end),
                    "limit": limit,
                },
            )
        )

    async def query_prometheus_range(
        self, *, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> ToolResult:
        return self._tool_result(
            await self._call(
                "query_prometheus",
                {
                    "query": query,
                    "start": self._time(start),
                    "end": self._time(end),
                    "step_seconds": step_seconds,
                },
            )
        )

    async def search_tempo_traces(
        self, *, query: str, start: datetime, end: datetime, limit: int
    ) -> ToolResult:
        return self._tool_result(
            await self._call(
                "search_tempo_traces",
                {
                    "query": query,
                    "start": self._time(start),
                    "end": self._time(end),
                    "limit": limit,
                },
            )
        )

    async def get_tempo_trace(
        self,
        *,
        trace_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ToolResult:
        arguments: dict[str, Any] = {"trace_id": trace_id}
        if start is not None:
            arguments["start"] = self._time(start)
        if end is not None:
            arguments["end"] = self._time(end)
        return self._tool_result(await self._call("get_tempo_trace", arguments))

    async def query_elasticsearch_logs(
        self,
        *,
        query: str,
        service: str | None,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> ToolResult:
        return self._tool_result(
            await self._call(
                "query_elasticsearch_logs",
                {
                    "query": query,
                    "service": service,
                    "start": self._time(start),
                    "end": self._time(end),
                    "limit": limit,
                },
            )
        )

    async def inspect_kubernetes(
        self,
        *,
        inspection: str,
        cluster: str | None,
        namespace: str | None,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        return self._tool_result(
            await self._call(
                "inspect_kubernetes",
                {
                    "inspection": inspection,
                    "cluster": cluster,
                    "namespace": namespace,
                    "start": self._time(start),
                    "end": self._time(end),
                },
            )
        )

    async def test_connection(self, datasource: DatasourceConfig) -> tuple[bool, str]:
        payload = await self._call("probe_datasource", {"datasource_id": datasource.id})
        return bool(payload.get("ok")), str(payload.get("message", ""))[:500]

    async def _call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        async with Client(
            self._transport(),
            raise_exceptions=True,
            read_timeout_seconds=float(self.settings.datasource_timeout_seconds),
        ) as client:
            result = await client.call_tool(name, dict(arguments))
        if result.is_error:
            message = " ".join(str(getattr(item, "text", "")) for item in result.content).strip()
            raise RuntimeError(message or f"MCP tool failed: {name}")
        payload = result.structured_content
        if not isinstance(payload, dict):
            raise RuntimeError(f"MCP tool returned no structured result: {name}")
        if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > 2_000_000:
            raise RuntimeError("MCP 工具返回内容超过 2 MB 安全上限")
        return cast(dict[str, Any], payload)

    @asynccontextmanager
    async def _transport(self) -> AsyncIterator[TransportStreams]:
        headers = {
            "Authorization": f"Bearer {self.settings.mcp_internal_token}",
            "X-YiOps-Tenant-ID": current_tenant_id() or DEFAULT_TENANT_ID,
        }
        timeout = httpx2.Timeout(
            float(self.settings.datasource_timeout_seconds),
            read=float(self.settings.datasource_timeout_seconds),
        )
        async with httpx2.AsyncClient(headers=headers, timeout=timeout, trust_env=False) as http:
            async with streamable_http_client(
                self.settings.mcp_url,
                http_client=http,
                terminate_on_close=False,
            ) as streams:
                yield streams

    @staticmethod
    def _tool_result(payload: Mapping[str, Any]) -> ToolResult:
        return ToolResult(
            source=payload["source"],
            query_pack=str(payload["query_pack"]),
            template_id=str(payload["template_id"]),
            status=str(payload["status"]),
            result_count=int(payload.get("result_count", 0)),
            data=dict(payload.get("data", {})),
            duration_ms=int(payload.get("duration_ms", 0)),
            error_code=str(payload["error_code"]) if payload.get("error_code") else None,
        )

    @staticmethod
    def _time(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _is_number(value: object) -> bool:
        try:
            float(value)  # type: ignore[arg-type]
            return True
        except (TypeError, ValueError):
            return False
