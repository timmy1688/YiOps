# YiOps Agent 分析流程

本文档说明 YiOps Agent 的工作原理、一次分析如何运行，以及后续技术演进方向。

核心实现：

- `backend/app/services/incidents.py`：告警去重、聚合和恢复；
- `backend/app/runtime/supervisor.py`：任务队列、并发控制和启动恢复；
- `backend/app/agents/graph.py`：LangGraph 八节点分析流程；
- `backend/app/tools/catalog.py`：受控 QueryPack 和查询模板；
- `backend/app/analysis/evidence.py`：证据压缩、脱敏和评分；
- `backend/app/llm/deepseek.py`：模型规划、补证和根因分析。

## 1. Agent 原理

YiOps Agent 本质上是一个**会根据现场情况选择调查动作的程序流程**，不是让大模型直接连接生产环境
自由操作。

它会读取告警、选择调查方向、调用只读工具、查看查询结果、补充一次证据，最后形成根因假设。整个过程
由四部分协作：

| 组件 | 负责什么 |
|---|---|
| LLM | 选择调查方向、检查证据缺口、关联证据并生成根因假设 |
| Python | 查询真实数据、压缩证据、校验引用、限制权限和置信度 |
| LangGraph | 按顺序执行节点，在节点之间传递状态 |
| MySQL | 保存任务、工具调用、Evidence 和报告，支持审计与恢复 |

核心原则：

1. **先取证，再分析**：告警只是线索，根因结论必须回到实际查询结果；
2. **模型做判断，程序守边界**：LLM 处理模糊推理，Python 处理查询、计算和验证；
3. **有限自主**：模型只能选择白名单 QueryPack，不能写任意查询或执行修复；
4. **多源验证**：关联指标、日志、Kubernetes 状态和 Elasticsearch 事件；
5. **允许不知道**：证据不足时返回 `insufficient_evidence`，不强行生成根因；
6. **过程可追溯**：每次查询、证据和报告引用都持久化。

## 2. 一次分析如何运行

```mermaid
flowchart LR
    A[Alertmanager 告警] --> B[去重并聚合 Incident]
    B --> C[创建 AnalysisRun]
    C --> D[后台 Worker]
    D --> E[整理现场]
    E --> F[模型选择调查方向]
    F --> G[程序查询真实数据]
    G --> H[生成 Evidence]
    H --> I[检查是否需要补查]
    I --> J[模型生成根因假设]
    J --> K[程序验证报告]
    K --> L[保存并展示]
```

### 2.1 告警进入系统

Alertmanager 可能重复发送相同告警，也可能同时发送同一故障引起的多条告警。后端先完成：

1. 合并公共标签和单条告警标签；
2. 使用 fingerprint 和开始时间去重；
3. 按服务、集群、namespace、告警名称和 10 分钟时间桶生成聚合键；
4. 将相关活动告警归入同一个 `Incident`。

服务名按以下顺序识别：

```text
service label → app label → job label → unknown-service
```

满足以下条件时自动创建 `AnalysisRun`：告警为 `firing`、Incident 为 `open`、渠道开启自动分析，并且
该 Incident 还没有分析任务。也可以手动创建任务；已有 `queued` 或 `running` 任务时不会重复执行。

### 2.2 后台启动分析

`AnalysisSupervisor` 将任务放入 `asyncio.Queue`，固定数量的 Worker 负责执行。队列控制并发，数据库
保存任务进度，因此页面关闭不会中断分析，应用重启后未完成任务也能重新入队。

### 2.3 八个 Agent 节点

```text
normalize → plan → collect → compress → refine → analyze → validate → save
```

| 节点 | 执行者 | 实际动作 | 产物 |
|---|---|---|---|
| `normalize` | Python | 整理服务、实例、集群、告警和时间窗 | Incident 上下文 |
| `plan` | LLM | 只选择要检查的 QueryPack，不直接猜根因 | 首轮调查计划 |
| `collect` | Python | 将 QueryPack 转成固定模板，并行查询数据源 | ToolExecution |
| `compress` | Python | 统计指标、提取日志样本、脱敏和去重 | Evidence |
| `refine` | LLM + Python | 判断是否漏查关键方向，最多补查一次 | 补充 Evidence |
| `analyze` | LLM | 基于 Evidence 生成根因假设、反证和建议 | 结构化报告 |
| `validate` | Python / LLM | 校验证据引用并限制置信度，引用错误时修正一次 | 已验证报告 |
| `save` | Python | 保存报告和状态，通过 SSE 通知前端 | RootCauseReport |

正常运行调用模型 3 次：调查规划、证据缺口复核和根因分析。只有证据引用验证失败时，才会进行第 4 次
修正调用。本地规则模式不调用外部模型。

### 2.4 一个完整例子

假设收到 `payments-api` 的 `KubePodCrashLooping` 告警：

1. 系统将重复告警聚合成一个 Incident，并创建后台任务；
2. 模型选择 `kubernetes_cluster` 和 `application_errors`；
3. Python 查询到 Pod 为 `CrashLoopBackOff`，Loki 中出现 `DATABASE_URL is missing`，健康实例数
   从 3 降到 0；
4. 程序将三项结果压缩成 `k8s_01`、`log_02` 和 `metric_03` 三条 Evidence；
5. 模型判断当前证据足够，不再补查；
6. 模型生成“数据库连接配置缺失导致应用启动失败”的根因假设，并引用上述 Evidence；
7. Python 确认证据 ID 真实存在，下调过高置信度，并保存报告；
8. 报告同时指出还未直接检查 Deployment、ConfigMap 或 Secret，因此这仍是有证据支持的假设，而不是
   无条件确认的事实。

整个数据变化过程是：

```text
AlertEvent
→ Incident
→ InvestigationPlan
→ ToolExecution
→ Evidence
→ RootCauseReport
```

## 3. 查询、证据和报告

### 3.1 受控查询

模型只能选择以下 QueryPack：

| QueryPack | 调查内容 |
|---|---|
| `kubernetes_cluster` | Pod、工作负载、节点、Event、重启和错误日志 |
| `service_health` | 请求量、错误率和 P99 延迟 |
| `runtime_resource` | 进程 CPU 和内存 |
| `instance_health` | 健康实例数 |
| `dependency_health` | 下游错误率和延迟 |
| `database_symptom` | 连接池和数据库超时日志 |
| `application_errors` | Loki 和 Elasticsearch 应用错误 |

Python 将 QueryPack 映射为 `catalog.py` 中的固定模板，并自动填入服务、集群、namespace 和时间范围。
默认查询告警前 60 分钟到告警后至少 30 分钟，最长不超过告警开始后 6 小时。

所有查询并发执行并记录参数、状态、耗时、结果数量和错误码。`collection_summary` 明确区分“查询成功但
没有结果”和“数据源不可用”，避免模型把没查到数据误判为系统正常。

### 3.2 Evidence

只有成功且非空的查询结果才生成 Evidence：

- 指标：计算前后平均值、峰值和变化率；
- 日志：限制样本数量和长度，提取错误模式；
- Kubernetes：保留异常对象、容器状态、重启数和 Warning Event；
- 敏感内容：对 authorization、token、password、secret 和 Bearer Token 脱敏；
- 重复内容：使用 `content_hash` 去重。

Evidence 统一带有 ID、类型、来源、摘要、观测时间、质量分和工具执行 ID。程序按质量、异常程度和与
告警时间的距离排序，默认最多向模型提供 30 条；完整原始日志不会直接发送给模型。

### 3.3 报告与验证

模型输出包括：

```json
{
  "summary": "应用因数据库连接配置缺失而持续启动失败",
  "confidence": 0.85,
  "hypotheses": [
    {
      "cause": "DATABASE_URL 未配置",
      "confidence": 0.85,
      "supporting_evidence_ids": ["log_02", "k8s_01"],
      "contradicting_evidence_ids": [],
      "missing_evidence": ["实际环境变量配置"]
    }
  ],
  "recommended_actions": ["检查 Deployment、ConfigMap 和 Secret"],
  "missing_evidence": ["数据库连通性检查"]
}
```

Python 验证输出 Schema、Evidence ID 和支持证据。置信度不能完全由模型自行决定：

- 无 Evidence：总体上限 0.20；
- 有 Evidence：基础上限 0.65；
- 证据更多、覆盖多个数据源时逐步提高；
- 单个假设只有一条支持证据时，该假设不超过 0.72；
- 总体最高不超过 0.93；
- 缺少跨数据源验证时，报告自动标记证据缺口。

## 4. 当前使用的 Agent 技术

| 技术 | 在 YiOps 中的用法 |
|---|---|
| Stateful Workflow | LangGraph 编排节点并传递 `AgentState` |
| Planning | 模型根据 Incident 选择 QueryPack |
| Tool Use | Python 执行预定义 PromQL、LogQL、Kubernetes 和 Elasticsearch 查询 |
| Parallel Execution | `asyncio.gather` 并发访问多个数据源 |
| Context Engineering | 聚合、采样、Top-K、脱敏和去重 |
| Evidence Grounding | 根因假设引用真实 Evidence ID |
| Reflection | 模型进行一次受限的证据缺口复核 |
| Structured Output | JSON Schema 和 Pydantic 约束模型输出 |
| Guardrails | 查询白名单、只读权限、引用校验和置信度上限 |
| Memory | `AgentState` 保存短期状态，MySQL 保存运行轨迹 |
| Observability / Eval | 记录节点、工具、Token 和证据，并运行 RCA 评测 |

当前没有使用开放式 ReAct、多 Agent、历史事故 RAG、GraphRAG、长期语义记忆、因果图、在线强化学习、
MCP 或自动修复。这些能力只有在评测证明收益后才会引入。

## 5. 恢复与安全边界

### 5.1 任务恢复

- 应用启动时重新入队 `queued` 和 `running` 任务；
- 已保存的调查计划、工具结果和报告会被复用；
- 相同模板在同一次运行中不会重复查询；
- 只有失败任务允许调用 retry API；
- SSE 每 15 秒发送心跳，断线后前端可通过 REST 恢复状态。

### 5.2 Incident 恢复

Alertmanager 需要配置 `send_resolved: true`。收到恢复通知后，系统更新对应 AlertEvent；当 Incident 下
所有关联告警都恢复时，将 Incident 标记为 `resolved`。恢复通知不会创建新的分析任务。

### 5.3 安全边界

- Agent 只执行代码中登记的查询模板；
- 模型不能直接访问数据源、凭据或网络；
- Kubernetes 和其他数据源使用只读凭据；
- 告警、日志和 Evidence 都按不可信数据处理；
- 日志进入模型前采样、截断和脱敏；
- 工具调用、Evidence、Token 和报告引用均可审计；
- 当前版本不会修改 Kubernetes、数据库或其他外部系统。

## 6. 技术演进路线

目标不是简单增加模型或 Agent 数量，而是逐步建立：

```text
统一遥测与变更上下文
→ 主动验证根因假设
→ 时序拓扑与因果排名
→ 独立验证和历史经验
→ 安全的修复闭环
```

| 阶段 | 主要建设 | 目标 |
|---|---|---|
| P0：评测与数据底座 | 实战故障注入、隐藏评测集、trajectory replay、OpenTelemetry Trace、发布和配置变更 | 先保证数据完整，并能客观衡量改进 |
| P1：主动调查 | Hypothesis Board、动态补证、查询预算、停止条件、服务拓扑和时序因果排名 | 从固定套餐查询升级为主动验证假设 |
| P2：知识与协作 | 时态知识图谱、历史事故记忆、GraphRAG、独立 Verifier、按领域拆分的专家 Agent | 处理跨服务、跨数据源和复杂传播故障 |
| P3：学习与修复 | 离线微调、偏好学习、shadow/canary、人工审批和自动回滚 | 用已确认事故优化策略，逐级开放修复能力 |

优先级上，Trace、变更事件、评测环境和 Hypothesis Board 应早于多 Agent 与 GraphRAG。多 Agent 只能
通过共享 Evidence ID 协作，历史事故只能提供候选假设，二者都不能替代当前故障的实时证据。

自动修复必须最后开放，并经过：

```text
结构化修复计划
→ Policy 校验
→ dry-run / 沙箱验证
→ 人工审批
→ 小范围 canary
→ 观察 SLO
→ 扩大执行或自动回滚
```

相关研究与标准：

- [OpenTelemetry 规范](https://opentelemetry.io/docs/specs/otel/overview/)
- [OpenRCA](https://proceedings.iclr.cc/paper_files/paper/2025/hash/d29b8d53678015079e1d245c023e49d2-Abstract-Conference.html)
- [AIOpsLab](https://microsoft.github.io/AIOpsLab/)
- [SREGym](https://arxiv.org/abs/2605.07161)
- [微服务因果 RCA 方法评测](https://arxiv.org/abs/2408.13729)
- [GraphRAG](https://arxiv.org/abs/2404.16130)
