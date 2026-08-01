#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.scoring import aggregate, score_prediction  # noqa: I001


RULES = [
    (("missing db_url", "configmap", "environment variable"), "ConfigMap 环境变量缺失"),
    (
        ("too many connections", "pool exhausted", "connection timeout"),
        "数据库连接池耗尽",
    ),
    (("diskpressure", "no space left", "evicted"), "节点磁盘压力导致 Pod 驱逐"),
    (("oomkilled", "out of memory", "memory limit"), "容器内存限制触发 OOMKilled"),
    (("certificate expired", "x509", "tls handshake"), "TLS 证书过期"),
    (("dns", "name resolution", "servfail"), "DNS 解析故障"),
    (("imagepullbackoff", "manifest unknown"), "镜像版本不存在导致拉取失败"),
    (("throttl", "cpu limit"), "CPU 限流导致服务延迟"),
    (("readiness probe", "connection refused"), "Readiness 探针配置错误"),
    (("deadlock", "lock wait"), "数据库锁竞争或死锁"),
]


def baseline(scenario: dict[str, Any]) -> dict[str, Any]:
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


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for file in sorted(path.glob("*.json")):
        value = json.loads(file.read_text(encoding="utf-8"))
        scenarios.extend(value if isinstance(value, list) else [value])
    return scenarios


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the YiOps RCA benchmark")
    parser.add_argument("--scenarios", type=Path, default=ROOT / "evals" / "scenarios")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "results.json")
    args = parser.parse_args()
    scenarios = load_scenarios(args.scenarios)
    supplied = (
        json.loads(args.predictions.read_text(encoding="utf-8"))
        if args.predictions
        else {}
    )
    rows = []
    for scenario in scenarios:
        prediction = supplied.get(scenario["id"]) or baseline(scenario)
        rows.append(
            {
                "scenario_id": scenario["id"],
                "category": scenario["category"],
                "prediction": prediction,
                "metrics": score_prediction(scenario, prediction),
            }
        )
    report = {
        "benchmark": "yiops-rca-v1",
        "scenario_count": len(rows),
        "aggregate": aggregate([row["metrics"] for row in rows]),
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(f"Scored {len(rows)} scenarios; report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
