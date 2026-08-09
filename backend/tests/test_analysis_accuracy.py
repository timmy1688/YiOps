from datetime import UTC, datetime, timedelta

import pytest

from app.agents.domain import QueryTemplate, ToolResult
from app.agents.rca import (
    _calibrate_confidence,
    _collection_summary,
    _evidence_relevance,
    _investigation_window,
)
from app.analysis.evidence import build_evidence
from app.config import Settings
from app.connectors.datasources import DatasourceGateway
from app.models import DatasourceConfig
from app.schemas import Hypothesis, InvestigationRefinement, RootCauseOutput


def test_investigation_window_includes_baseline_and_caps_long_incidents() -> None:
    started_at = datetime(2026, 7, 29, 10, tzinfo=UTC)
    start, end = _investigation_window(
        {
            "started_at": started_at.isoformat(),
            "ended_at": (started_at + timedelta(days=1)).isoformat(),
        }
    )

    assert start == started_at - timedelta(hours=1)
    assert end == started_at + timedelta(hours=6)


def test_evidence_relevance_rewards_temporal_anomalies() -> None:
    started_at = "2026-07-29T10:00:00+00:00"
    baseline = {
        "quality": 0.8,
        "values": {"change_percent": 0},
        "observed_at": "2026-07-29T08:00:00+00:00",
    }
    correlated = {
        "quality": 0.8,
        "values": {"change_percent": 180},
        "observed_at": "2026-07-29T10:05:00+00:00",
    }

    assert _evidence_relevance(correlated, started_at) > _evidence_relevance(
        baseline,
        started_at,
    )


def test_confidence_is_capped_without_cross_source_confirmation() -> None:
    report = RootCauseOutput(
        summary="数据库连接池耗尽",
        confidence=0.96,
        hypotheses=[
            Hypothesis(
                cause="数据库连接池耗尽",
                confidence=0.95,
                supporting_evidence_ids=["metric-1"],
            )
        ],
        recommended_actions=["检查连接池"],
        missing_evidence=[],
    )

    calibrated = _calibrate_confidence(
        report,
        [{"id": "metric-1", "source": "prometheus", "quality": 0.95}],
    )

    assert calibrated.confidence == 0.65
    assert calibrated.hypotheses[0].confidence == 0.65
    assert "缺少跨数据源交叉验证" in calibrated.missing_evidence


def test_refinement_can_decide_no_more_queries_are_needed() -> None:
    assert InvestigationRefinement().query_packs == []


def test_collection_summary_keeps_empty_and_failed_coverage() -> None:
    summary = _collection_summary(
        [
            {
                "template_id": "application_error_logs",
                "source": "loki",
                "status": "failed",
                "result_count": 0,
                "error_code": "CONNECTION_FAILED",
            }
        ]
    )

    assert summary == [
        {
            "template_id": "application_error_logs",
            "source": "loki",
            "status": "failed",
            "result_count": 0,
            "error_code": "CONNECTION_FAILED",
        }
    ]


@pytest.mark.asyncio
async def test_missing_optional_datasource_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyQuery:
        async def order_by(self, *_fields: str) -> list[DatasourceConfig]:
            return []

    monkeypatch.setattr(
        DatasourceConfig,
        "filter",
        lambda **_filters: EmptyQuery(),
    )

    client = DatasourceGateway(Settings())

    assert await client._get_datasource("elasticsearch") is None


def test_tempo_trace_result_builds_distributed_trace_evidence() -> None:
    template = QueryTemplate(
        id="application_error_traces",
        query_pack="application_errors",
        source="tempo",
        query='{ resource.service.name = "{service}" && status = error }',
        kind="trace",
        title="Application error traces",
    )
    result = ToolResult(
        source="tempo",
        query_pack="application_errors",
        template_id=template.id,
        status="completed",
        result_count=1,
        data={
            "traces": [
                {
                    "trace_id": "0123456789abcdef0123456789abcdef",
                    "root_service_name": "checkout",
                    "root_trace_name": "POST /checkout",
                    "start_time": "2026-08-08T10:00:00+00:00",
                    "duration_ms": 3200,
                }
            ]
        },
    )

    evidence = build_evidence(
        result,
        template,
        service="checkout",
        tool_execution_id="tool-1",
    )

    assert evidence is not None
    assert evidence.type == "distributed_trace"
    assert evidence.source == "tempo"
    assert "0123456789abcdef" in evidence.summary
