from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.connectors.datasources import DatasourceGateway
from app.models import DatasourceConfig


def test_tempo_trace_summary_normalizes_search_response() -> None:
    client = DatasourceGateway(Settings())

    summary = client._tempo_trace_summary(
        {
            "traceID": "0123456789abcdef0123456789abcdef",
            "rootServiceName": "checkout",
            "rootTraceName": "POST /checkout",
            "startTimeUnixNano": "1786183200000000000",
            "durationMs": 428,
            "spanSets": [{"matched": 2}],
        }
    )

    assert summary["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert summary["root_service_name"] == "checkout"
    assert summary["duration_ms"] == 428
    assert summary["matched_spans"] == 2
    assert summary["start_time"].startswith("2026-")


def test_tempo_otlp_trace_is_bounded_and_redacted() -> None:
    client = DatasourceGateway(Settings())
    raw_spans = [
        {
            "spanId": f"{index:016x}",
            "name": f"span-{index}",
            "startTimeUnixNano": "1786183200000000000",
            "endTimeUnixNano": "1786183200428000000",
            "attributes": [
                {
                    "key": "error.message",
                    "value": {"stringValue": "authorization=secret-token"},
                },
                {"key": "api.token", "value": {"stringValue": "opaque-value"}},
            ],
            "status": {"code": "STATUS_CODE_ERROR"},
        }
        for index in range(3)
    ]
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]
                },
                "scopeSpans": [{"spans": raw_spans}],
            }
        ]
    }

    spans, total = client._tempo_spans(payload, limit=2)

    assert total == 3
    assert len(spans) == 2
    assert spans[0]["service_name"] == "checkout"
    assert spans[0]["duration_ms"] == 428.0
    assert spans[0]["attributes"]["error.message"] == "[REDACTED]"
    assert spans[0]["attributes"]["api.token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_tempo_search_mock_and_trace_id_validation() -> None:
    client = DatasourceGateway(Settings(datasource_mock_mode=True))
    now = datetime.now(UTC)

    result = await client.search_tempo_traces(
        query="{ status = error }",
        start=now,
        end=now,
        limit=10,
    )

    assert result.source == "tempo"
    assert result.template_id == "chat_tempo_search"
    assert result.result_count == 1
    with pytest.raises(ValueError, match="trace ID"):
        await client.get_tempo_trace(trace_id="not-a-trace-id")


def test_tempo_native_auth_uses_encrypted_bearer_token() -> None:
    client = DatasourceGateway(Settings())
    datasource = DatasourceConfig(
        id="ds_tempo",
        tenant_id="tenant_default",
        name="Tempo",
        type="tempo",
        base_url="http://tempo:3200",
        secret_ref=client.vault.encrypt({"token": "tempo-token"}),
        settings={"tenant_id": "ops", "auth_type": "bearer"},
        enabled=True,
    )

    headers, auth = client._request_auth(datasource, client.vault.decrypt(datasource.secret_ref))

    assert headers == {"Authorization": "Bearer tempo-token"}
    assert auth is None


@pytest.mark.asyncio
async def test_tempo_search_calls_native_read_only_api() -> None:
    client = DatasourceGateway(Settings(datasource_mock_mode=False))
    datasource = DatasourceConfig(
        id="ds_tempo",
        tenant_id="tenant_default",
        name="Tempo",
        type="tempo",
        base_url="http://tempo:3200",
        settings={"tenant_id": "ops", "auth_type": "none"},
        enabled=True,
    )

    calls: list[tuple[str, str, dict[str, object]]] = []

    async def fake_request(
        datasource: DatasourceConfig,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: dict[str, object] | None = None,
    ) -> dict[str, object]:
        calls.append((method, path, params or {}))
        return {
            "traces": [
                {
                    "traceID": "0123456789abcdef0123456789abcdef",
                    "rootServiceName": "checkout",
                    "rootTraceName": "POST /checkout",
                    "startTimeUnixNano": "1786183200000000000",
                    "durationMs": 428,
                }
            ],
            "metrics": {"inspectedTraces": 12},
        }

    client._request_json = fake_request  # type: ignore[method-assign]
    start = datetime(2026, 8, 8, 9, tzinfo=UTC)
    end = datetime(2026, 8, 8, 10, tzinfo=UTC)

    traces, metrics = await client._tempo_search(
        datasource,
        query="{ status = error }",
        start=start,
        end=end,
        limit=10,
    )

    method, path, arguments = calls[0]
    assert method == "GET"
    assert path == "/api/search"
    assert arguments["q"] == "{ status = error }"
    assert arguments["limit"] == 10
    assert traces[0]["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert metrics == {"inspectedTraces": 12}
