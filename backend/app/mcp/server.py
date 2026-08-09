from __future__ import annotations

import hmac
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Any

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.agents.domain import ToolResult
from app.config import get_settings
from app.connectors.datasources import DatasourceGateway
from app.db import close_db, init_db
from app.models import DatasourceConfig
from app.security.tenant import current_tenant_id, tenant_scope

settings = get_settings()
gateway = DatasourceGateway(settings)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


@asynccontextmanager
async def lifespan(_: MCPServer[Any]) -> AsyncIterator[dict[str, Any]]:
    await init_db()
    try:
        yield {}
    finally:
        await close_db()


server = MCPServer(
    "yiops-observability",
    instructions=(
        "YiOps 内部统一可观测性查询服务。所有工具均为只读工具，租户由可信 HTTP 请求头确定。"
    ),
    lifespan=lifespan,
)


def _result(value: ToolResult) -> dict[str, Any]:
    return asdict(value)


@server.tool(annotations=READ_ONLY, structured_output=True)
async def query_prometheus(
    query: str,
    start: datetime,
    end: datetime,
    step_seconds: int = 30,
) -> dict[str, Any]:
    """执行受限的 Prometheus 区间查询。"""
    return _result(
        await gateway.query_prometheus_range(
            query=query, start=start, end=end, step_seconds=step_seconds
        )
    )


@server.tool(annotations=READ_ONLY, structured_output=True)
async def query_loki_logs(
    query: str,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> dict[str, Any]:
    """执行受限的 Loki 日志区间查询。"""
    return _result(await gateway.query_loki_logs(query=query, start=start, end=end, limit=limit))


@server.tool(annotations=READ_ONLY, structured_output=True)
async def search_tempo_traces(
    query: str,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> dict[str, Any]:
    """用 TraceQL 搜索 Tempo trace。"""
    return _result(
        await gateway.search_tempo_traces(query=query, start=start, end=end, limit=limit)
    )


@server.tool(annotations=READ_ONLY, structured_output=True)
async def get_tempo_trace(
    trace_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """按 trace ID 获取 Tempo trace。"""
    return _result(await gateway.get_tempo_trace(trace_id=trace_id, start=start, end=end))


@server.tool(annotations=READ_ONLY, structured_output=True)
async def query_elasticsearch_logs(
    query: str,
    start: datetime,
    end: datetime,
    service: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """在 Elasticsearch 日志索引执行只读搜索。"""
    return _result(
        await gateway.query_elasticsearch_logs(
            query=query, service=service, start=start, end=end, limit=limit
        )
    )


@server.tool(annotations=READ_ONLY, structured_output=True)
async def inspect_kubernetes(
    inspection: str,
    start: datetime,
    end: datetime,
    cluster: str | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """检查异常 Pod、工作负载、节点或 Warning 事件。"""
    return _result(
        await gateway.inspect_kubernetes(
            inspection=inspection,
            cluster=cluster,
            namespace=namespace,
            start=start,
            end=end,
        )
    )


@server.tool(annotations=READ_ONLY, structured_output=True)
async def probe_datasource(datasource_id: str) -> dict[str, Any]:
    """验证当前租户指定数据源的原生 API 连接。"""
    if not re.fullmatch(r"ds_[0-9a-f]{32}", datasource_id):
        raise ValueError("datasource_id 无效")
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise RuntimeError("缺少租户上下文")
    datasource = await DatasourceConfig.get_or_none(id=datasource_id, tenant_id=tenant_id)
    if datasource is None:
        raise ValueError("数据源不存在")
    ok, message = await gateway.test_connection(datasource)
    return {"ok": ok, "message": message}


@server.custom_route("/health", methods=["GET"], include_in_schema=False)  # type: ignore[untyped-decorator]
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "yiops-mcp"})


class InternalAuthMiddleware:
    """Bridge trusted internal HTTP metadata into YiOps tenant context.

    MCP protocol handling, transport, validation, and tool dispatch remain owned by
    the official SDK; this middleware only enforces the deployment-local service
    token and establishes the application tenant context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        expected = f"Bearer {settings.mcp_internal_token}"
        if not hmac.compare_digest(headers.get("authorization", ""), expected):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        tenant_id = headers.get("x-yiops-tenant-id", "").strip()
        if (
            not tenant_id
            or len(tenant_id) > 128
            or not re.fullmatch(r"[A-Za-z0-9_.:-]+", tenant_id)
        ):
            await JSONResponse({"error": "invalid tenant"}, status_code=400)(scope, receive, send)
            return
        with tenant_scope(tenant_id):
            await self.app(scope, receive, send)


app = InternalAuthMiddleware(
    server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=settings.mcp_host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["yiops-mcp:*", "127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[],
        ),
    )
)


def main() -> None:
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
