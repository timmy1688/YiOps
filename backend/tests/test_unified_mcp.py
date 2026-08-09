import pytest
from mcp_types import CallToolResult

from app.config import Settings
from app.mcp.server import gateway, server


@pytest.mark.asyncio
async def test_unified_mcp_exposes_only_fixed_read_only_tools() -> None:
    tools = await server.list_tools()

    assert {tool.name for tool in tools} == {
        "query_prometheus",
        "query_loki_logs",
        "search_tempo_traces",
        "get_tempo_trace",
        "query_elasticsearch_logs",
        "inspect_kubernetes",
        "probe_datasource",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)
    assert all(tool.annotations and tool.annotations.destructive_hint is False for tool in tools)


@pytest.mark.asyncio
async def test_unified_mcp_returns_structured_tool_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "settings", Settings(datasource_mock_mode=True))

    result = await server.call_tool(
        "query_prometheus",
        {
            "query": "up",
            "start": "2026-08-09T00:00:00Z",
            "end": "2026-08-09T01:00:00Z",
            "step_seconds": 30,
        },
    )

    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["source"] == "prometheus"
    assert result.structured_content["status"] == "completed"
