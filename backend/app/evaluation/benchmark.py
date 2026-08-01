import json
import time
from pathlib import Path
from typing import Any

from app.evaluation.scoring import aggregate, score_prediction

BENCHMARK_PATH = (
    Path(__file__).resolve().parents[3] / "evals" / "scenarios" / "rca-benchmark-v1.json"
)

RULES = [
    (("missing db_url", "configmap", "environment variable"), "ConfigMap 环境变量缺失"),
    (("too many connections", "pool exhausted", "connection timeout"), "数据库连接池耗尽"),
    (("diskpressure", "no space left", "evicted"), "节点磁盘压力导致 Pod 驱逐"),
    (("oomkilled", "out of memory", "memory limit"), "容器内存限制触发 OOMKilled"),
    (("certificate expired", "x509", "tls handshake"), "TLS 证书过期"),
    (("dns", "name resolution", "servfail"), "DNS 解析故障"),
    (("imagepullbackoff", "manifest unknown"), "镜像版本不存在导致拉取失败"),
    (("throttl", "cpu limit"), "CPU 限流导致服务延迟"),
    (("readiness probe", "connection refused"), "Readiness 探针配置错误"),
    (("deadlock", "lock wait"), "数据库锁竞争或死锁"),
]


def load_scenarios(path: Path = BENCHMARK_PATH) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("RCA benchmark must contain a JSON list")
    return value


def baseline_prediction(scenario: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    observations = scenario.get("observations", [])
    corpus = " ".join(str(item.get("summary", "")).lower() for item in observations)
    cause = "证据不足，尚不能确定根因"
    matched_terms: tuple[str, ...] = ()
    for terms, candidate in RULES:
        if any(term in corpus for term in terms):
            cause = candidate
            matched_terms = terms
            break
    cited = [
        item["id"]
        for item in observations
        if any(term in str(item.get("summary", "")).lower() for term in matched_terms)
    ]
    source_count = len({item["source"] for item in observations if item["id"] in cited})
    confidence = min(0.55 + 0.12 * source_count, 0.91) if cited else 0.25
    return {
        "root_cause": cause,
        "confidence": confidence,
        "evidence_ids": cited,
        "claims": [{"text": cause, "evidence_ids": cited}],
        "latency_ms": (time.perf_counter() - started) * 1000,
        "tool_calls": len({item["source"] for item in observations}),
        "tokens": 0,
    }


def run_benchmark(
    predictions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scenario in load_scenarios():
        prediction = (predictions or {}).get(scenario["id"]) or baseline_prediction(scenario)
        rows.append(
            {
                "scenario_id": scenario["id"],
                "title": scenario["title"],
                "category": scenario["category"],
                "service": scenario["incident"]["service"],
                "alert": scenario["incident"]["alert"],
                "required_sources": scenario["expected"].get("required_sources", []),
                "prediction": prediction,
                "metrics": score_prediction(scenario, prediction),
            }
        )
    category_scores = {
        category: aggregate(
            [row["metrics"] for row in rows if row["category"] == category]
        )
        for category in sorted({str(row["category"]) for row in rows})
    }
    return {
        "benchmark": "yiops-rca-v1",
        "scenario_count": len(rows),
        "aggregate": aggregate([row["metrics"] for row in rows]),
        "categories": category_scores,
        "results": rows,
    }
