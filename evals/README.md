# YiOps RCA Benchmark

该评测集验证根因 Top-1、证据精确率/召回率、跨数据源覆盖、无证据声明率、
置信度 Brier 分数，以及延迟、工具调用和 Token 成本。

```bash
backend/.venv/bin/python evals/run.py
```

外部 Agent 可提交以场景 ID 为键的预测 JSON，并通过
`--predictions your-results.json` 使用同一评分器比较。预测字段见 `run.py` 的
`baseline()` 返回值。场景均为合成故障，不包含生产数据或密钥。
