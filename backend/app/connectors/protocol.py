from datetime import datetime
from typing import Protocol

from app.agents.domain import QueryTemplate, ToolResult


class DatasourceGatewayProtocol(Protocol):
    async def execute(
        self,
        template: QueryTemplate,
        *,
        service: str,
        start: datetime,
        end: datetime,
        cluster: str | None = None,
        namespace: str | None = None,
    ) -> ToolResult: ...

    async def query_loki_logs(
        self, *, query: str, start: datetime, end: datetime, limit: int
    ) -> ToolResult: ...

    async def query_prometheus_range(
        self, *, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> ToolResult: ...

    async def search_tempo_traces(
        self, *, query: str, start: datetime, end: datetime, limit: int
    ) -> ToolResult: ...

    async def get_tempo_trace(
        self,
        *,
        trace_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ToolResult: ...

    async def inspect_kubernetes(
        self,
        *,
        inspection: str,
        cluster: str | None,
        namespace: str | None,
        start: datetime,
        end: datetime,
    ) -> ToolResult: ...

    async def query_elasticsearch_logs(
        self,
        *,
        query: str,
        service: str | None,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> ToolResult: ...
