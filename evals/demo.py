#!/usr/bin/env python3
import argparse
import json

from run import ROOT, baseline

FEATURED = {
    "crashloop": "crashloop-config-001",
    "db-pool": "db-pool-001",
    "disk-pressure": "disk-pressure-001",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a featured YiOps RCA demo")
    parser.add_argument("demo", choices=FEATURED)
    args = parser.parse_args()
    scenarios = json.loads(
        (ROOT / "evals/scenarios/rca-benchmark-v1.json").read_text(encoding="utf-8")
    )
    scenario = next(item for item in scenarios if item["id"] == FEATURED[args.demo])
    print(f"# {scenario['title']}\n")
    print("## 观测证据")
    for item in scenario["observations"]:
        print(f"- [{item['source']}] {item['id']}: {item['summary']}")
    print("\n## 基线 Agent 结论")
    print(json.dumps(baseline(scenario), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
