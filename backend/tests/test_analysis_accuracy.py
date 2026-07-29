from datetime import UTC, datetime, timedelta

import pytest

from app.agents.graph import (
    _calibrate_confidence,
    _collection_summary,
    _evidence_relevance,
    _investigation_window,
)
from app.config import Settings
from app.connectors.client import DatasourceClient
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

    client = DatasourceClient(Settings())

    assert await client._get_datasource("elasticsearch") is None
