from app.connectors.registry import registry
from app.evaluation.benchmark import run_benchmark
from app.evaluation.scoring import aggregate, score_prediction


def test_score_prediction_tracks_grounding_and_calibration() -> None:
    scenario = {
        "observations": [
            {"id": "e1", "source": "loki"},
            {"id": "e2", "source": "kubernetes"},
            {"id": "noise", "source": "prometheus"},
        ],
        "expected": {
            "cause_keywords": ["configmap"],
            "relevant_evidence_ids": ["e1", "e2"],
            "required_sources": ["loki", "kubernetes"],
        },
    }
    prediction = {
        "root_cause": "ConfigMap 缺少 DB_URL",
        "confidence": 0.8,
        "evidence_ids": ["e1", "e2", "noise"],
        "claims": [
            {"text": "启动失败", "evidence_ids": ["e1"]},
            {"text": "已扩容", "evidence_ids": []},
        ],
    }
    result = score_prediction(scenario, prediction)
    assert result["root_cause_top1"] == 1
    assert result["evidence_precision"] == 2 / 3
    assert result["evidence_recall"] == 1
    assert result["source_recall"] == 1
    assert result["unsupported_claim_rate"] == 0.5
    assert result["brier_score"] == 0.04


def test_aggregate_returns_metric_means() -> None:
    assert aggregate([{"hit": 1.0}, {"hit": 0.0}]) == {"hit": 0.5}


def test_builtin_benchmark_is_complete_and_grounded() -> None:
    report = run_benchmark()

    assert report["benchmark"] == "yiops-rca-v1"
    assert report["scenario_count"] == 20
    assert len(report["results"]) == 20
    assert report["aggregate"]["root_cause_top1"] >= 0.9
    assert report["aggregate"]["unsupported_claim_rate"] == 0
    assert {"configuration", "database", "kubernetes", "resource"}.issubset(report["categories"])


def test_connector_registry_exposes_all_builtin_capabilities() -> None:
    connectors = {item.type: item for item in registry.all()}

    assert set(connectors) == {
        "prometheus",
        "loki",
        "tempo",
        "elasticsearch",
        "kubernetes",
    }
    assert "logs" in connectors["loki"].capabilities
    assert "traceql_search" in connectors["tempo"].capabilities
    assert "read_only" in connectors["kubernetes"].capabilities
    assert connectors["kubernetes"].credential_kind == "bearer"
