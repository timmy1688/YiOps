import json
from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import Settings
from app.models import AnalysisModelConfig
from app.schemas import QueryPackPlan, RootCauseOutput
from app.security.credentials import CredentialVault


@dataclass(slots=True)
class ModelResult[T: BaseModel]:
    value: T
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class ModelRuntime:
    client: AsyncOpenAI | None
    model_name: str
    is_local: bool


class DeepSeekClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.vault = CredentialVault()

    async def runtime(self) -> ModelRuntime:
        configured = await AnalysisModelConfig.get_or_none(id="default", enabled=True)
        if configured and configured.secret_ref:
            credential = self.vault.decrypt(configured.secret_ref).get("api_key", "")
            if credential:
                return ModelRuntime(
                    client=AsyncOpenAI(
                        api_key=credential,
                        base_url=configured.base_url,
                        timeout=60.0,
                    ),
                    model_name=configured.model_name,
                    is_local=False,
                )
        if not self.settings.llm_mock_mode and self.settings.deepseek_api_key:
            return ModelRuntime(
                client=AsyncOpenAI(
                    api_key=self.settings.deepseek_api_key,
                    base_url=self.settings.deepseek_base_url,
                    timeout=60.0,
                ),
                model_name=self.settings.deepseek_model,
                is_local=False,
            )
        return ModelRuntime(
            client=None,
            model_name="local-evidence-rules",
            is_local=True,
        )

    async def plan(self, incident: dict[str, object]) -> ModelResult[QueryPackPlan]:
        runtime = await self.runtime()
        if runtime.is_local or runtime.client is None:
            alert_name = str(incident.get("alert_name", "")).lower()
            kubernetes_keywords = ("kubernetes", "k8s", "cluster", "node", "pod")
            if any(keyword in alert_name for keyword in kubernetes_keywords):
                return ModelResult(value=QueryPackPlan(query_packs=["kubernetes_cluster"]))
            packs = ["service_health", "runtime_resource", "application_errors"]
            if any(keyword in alert_name for keyword in ("database", "db", "error", "latency")):
                packs.append("database_symptom")
            return ModelResult(value=QueryPackPlan(query_packs=packs))

        schema = QueryPackPlan.model_json_schema()
        system = (
            "You plan read-only incident investigations. Output JSON only. "
            "Choose the smallest useful set of allowed query_packs. "
            "Never create query text or new pack names."
        )
        response = await runtime.client.chat.completions.create(
            model=runtime.model_name,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"incident": incident, "output_schema": schema},
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=1000,
            extra_body={"thinking": {"type": "disabled"}},
        )
        value = QueryPackPlan.model_validate_json(response.choices[0].message.content or "{}")
        usage = response.usage
        return ModelResult(
            value=value,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def analyze(
        self,
        incident: dict[str, object],
        evidence: list[dict[str, object]],
        *,
        validation_error: str | None = None,
    ) -> ModelResult[RootCauseOutput]:
        runtime = await self.runtime()
        if runtime.is_local or runtime.client is None:
            return ModelResult(value=self._mock_report(incident, evidence))

        schema = RootCauseOutput.model_json_schema()
        system = (
            "You are an evidence-grounded SRE root cause analyst. Output JSON only. "
            "Write every narrative field in concise Simplified Chinese. "
            "Every evidence ID must exist in the supplied evidence list. "
            "Distinguish correlation from causation. If evidence is insufficient, "
            "state that clearly and keep confidence low. Recommendations must be read-only."
        )
        payload: dict[str, object] = {
            "incident": incident,
            "evidence": evidence[: self.settings.max_evidence_items],
            "output_schema": schema,
        }
        if validation_error:
            payload["previous_validation_error"] = validation_error
            payload["instruction"] = "Correct the invalid report once without inventing evidence."
        response = await runtime.client.chat.completions.create(
            model=runtime.model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            max_tokens=4000,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        value = RootCauseOutput.model_validate_json(response.choices[0].message.content or "{}")
        usage = response.usage
        return ModelResult(
            value=value,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    @staticmethod
    async def test_connection(
        *,
        api_key: str,
        base_url: str,
        model_name: str,
    ) -> str:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly OK to confirm connectivity.",
                }
            ],
            max_tokens=8,
        )
        content = response.choices[0].message.content or ""
        return f"模型响应正常：{content.strip()[:80] or 'OK'}"

    @staticmethod
    def _mock_report(
        incident: dict[str, object],
        evidence: list[dict[str, object]],
    ) -> RootCauseOutput:
        kubernetes_items = [
            item for item in evidence if str(item.get("title", "")).startswith("Kubernetes")
        ]
        if kubernetes_items:
            return DeepSeekClient._kubernetes_report(
                evidence,
                is_test=bool(incident.get("is_test")),
            )

        db_ids = [
            str(item["id"])
            for item in evidence
            if any(
                keyword in str(item.get("title", "")).lower()
                for keyword in ("database", "pool", "timeout")
            )
        ]
        error_ids = [
            str(item["id"]) for item in evidence if "error" in str(item.get("title", "")).lower()
        ]
        supporting = list(dict.fromkeys(db_ids + error_ids))[:5]
        if not supporting:
            supporting = [str(item["id"]) for item in evidence[:2]]
        if not supporting:
            return RootCauseOutput(
                summary="当前证据不足，无法确定根因",
                confidence=0.2,
                hypotheses=[],
                recommended_actions=["检查数据源配置和查询覆盖范围"],
                missing_evidence=["缺少有效指标与日志证据"],
            )
        return RootCauseOutput(
            summary="最可能的根因是数据库连接池耗尽，导致请求错误率和延迟上升",
            confidence=0.86,
            hypotheses=[
                {
                    "cause": "数据库连接池耗尽",
                    "confidence": 0.86,
                    "supporting_evidence_ids": supporting,
                    "contradicting_evidence_ids": [],
                    "missing_evidence": ["数据库慢查询明细"],
                }
            ],
            recommended_actions=[
                "检查数据库慢查询",
                "核对连接池上限、活动连接和等待线程",
            ],
            missing_evidence=["数据库慢查询明细"],
        )

    @staticmethod
    def _kubernetes_report(
        evidence: list[dict[str, object]],
        *,
        is_test: bool = False,
    ) -> RootCauseOutput:
        values_by_title: dict[str, float] = {}
        evidence_by_title: dict[str, dict[str, object]] = {}
        for item in evidence:
            title = str(item.get("title", ""))
            evidence_by_title[title] = item
            values = item.get("values", {})
            if isinstance(values, dict):
                values_by_title[title] = float(values.get("current", 0) or 0)

        not_ready_nodes = values_by_title.get("Kubernetes NotReady nodes", 0)
        abnormal_pods = values_by_title.get("Kubernetes abnormal pods", 0)
        unavailable_replicas = values_by_title.get("Kubernetes unavailable deployment replicas", 0)
        waiting_containers = values_by_title.get("Kubernetes waiting containers", 0)
        restarts = values_by_title.get("Kubernetes container restarts in 1h", 0)

        issues: list[str] = []
        supporting: list[str] = []
        issue_titles = {
            "Kubernetes NotReady nodes": not_ready_nodes,
            "Kubernetes abnormal pods": abnormal_pods,
            "Kubernetes unavailable deployment replicas": unavailable_replicas,
            "Kubernetes waiting containers": waiting_containers,
            "Kubernetes container restarts in 1h": restarts,
        }
        for title, value in issue_titles.items():
            item = evidence_by_title.get(title)
            if value > 0 and item:
                supporting.append(str(item["id"]))
        if not_ready_nodes > 0:
            issues.append(f"{not_ready_nodes:.0f} 个节点处于 NotReady")
        if abnormal_pods > 0:
            issues.append(f"{abnormal_pods:.0f} 个 Pod 处于异常阶段")
        if unavailable_replicas > 0:
            issues.append(f"{unavailable_replicas:.0f} 个 Deployment 副本不可用")
        if waiting_containers > 0:
            issues.append(f"{waiting_containers:.0f} 个容器正在等待启动")
        if restarts > 0:
            issues.append(f"最近 1 小时容器重启累计 {restarts:.0f} 次")

        log_items = [
            item
            for item in evidence
            if str(item.get("source", "")).lower() == "loki"
            or str(item.get("type", "")).lower() == "log_pattern"
        ]
        log_samples: list[str] = []
        for item in log_items:
            values = item.get("values", {})
            if isinstance(values, dict):
                samples = values.get("samples", [])
                if isinstance(samples, list):
                    log_samples.extend(str(sample) for sample in samples)
        log_text = "\n".join(log_samples).lower()
        log_patterns: list[str] = []
        if "failed to acquire lease" in log_text:
            log_patterns.append("CSI/控制器 Leader Election 持续抢锁失败")
        if "server could not find the requested resource" in log_text:
            log_patterns.append("集群组件请求了 API Server 不支持的资源版本")
        if "redis: transaction failed" in log_text:
            log_patterns.append("JuiceFS Redis 元数据事务出现重试")
        if "no route to host" in log_text:
            log_patterns.append("日志组件曾出现目标网络不可达")
        if log_patterns:
            supporting.extend(str(item["id"]) for item in log_items)

        api_items = [
            item for item in evidence if str(item.get("source", "")).lower() == "kubernetes"
        ]
        api_findings: dict[str, list[dict[str, object]]] = {}
        for item in api_items:
            values = item.get("values", {})
            raw_items = values.get("items", []) if isinstance(values, dict) else []
            api_findings[str(item.get("title", ""))] = [
                finding for finding in raw_items if isinstance(finding, dict)
            ]
        abnormal_pod_items = api_findings.get("Kubernetes API abnormal pods", [])
        workload_items = api_findings.get("Kubernetes API unhealthy workloads", [])
        node_items = api_findings.get("Kubernetes API unhealthy nodes", [])
        event_items = api_findings.get("Kubernetes API warning events", [])
        if api_items:
            supporting.extend(str(item["id"]) for item in api_items)
        supporting = list(dict.fromkeys(supporting))[:8]

        if api_items:
            exact_findings: list[str] = []
            for pod in abnormal_pod_items[:3]:
                exact_findings.append(
                    f"{pod.get('namespace', '-')}/{pod.get('name', 'unknown')}"
                    f"（{pod.get('reason') or pod.get('phase') or '未就绪'}）"
                )
            for workload in workload_items[:2]:
                exact_findings.append(
                    f"{workload.get('kind', 'Workload')}/"
                    f"{workload.get('name', 'unknown')}"
                    f"（就绪 {workload.get('ready', 0)}/{workload.get('desired', 0)}）"
                )
            for node in node_items[:2]:
                exact_findings.append(f"Node/{node.get('name', 'unknown')}（状态异常）")

            event_reasons = [str(item.get("reason")) for item in event_items if item.get("reason")]
            reason = event_reasons[0] if event_reasons else ""
            cause_by_reason = {
                "FailedScheduling": "Pod 调度条件不满足",
                "FailedMount": "存储卷挂载失败",
                "FailedAttachVolume": "存储卷附加失败",
                "ErrImagePull": "容器镜像拉取失败",
                "ImagePullBackOff": "容器镜像持续拉取失败",
                "BackOff": "容器启动后反复失败",
                "Unhealthy": "容器健康检查失败",
            }
            cause = cause_by_reason.get(
                reason,
                "Kubernetes 工作负载未就绪",
            )
            if abnormal_pod_items:
                first_reason = str(abnormal_pod_items[0].get("reason") or "")
                cause = cause_by_reason.get(first_reason, cause)

            first_event = event_items[0] if event_items else {}
            event_target = (
                f"{first_event.get('namespace', '-')}/"
                f"{first_event.get('object_kind', '对象')}/"
                f"{first_event.get('name', 'unknown')}"
            )
            event_message = str(first_event.get("message") or "")
            factors: list[str] = []
            if "Insufficient cpu" in event_message:
                factors.append("工作节点可分配 CPU 不足")
            if "untolerated taint" in event_message:
                factors.append("控制平面节点存在 Pod 未容忍的污点")
            if "Insufficient memory" in event_message:
                factors.append("工作节点可分配内存不足")
            if "didn't match" in event_message:
                factors.append("节点选择或亲和性条件不匹配")
            if "Liveness probe failed" in event_message:
                factors.append("组件存活探针检查失败")
            if "Client.Timeout exceeded" in event_message:
                factors.append("健康检查端点连接超时")
            if not factors and event_message:
                factors.append(event_message.split(":", 1)[0][:100])

            prefix = "本次为模拟告警，告警本身不代表真实故障。真实集群调查发现：" if is_test else ""
            if event_items:
                cause = f"{event_target}：{cause}"
                summary = (
                    f"{prefix}直接原因：{event_target} 出现"
                    f" {first_event.get('reason', 'Warning')}。"
                    f"底层原因：{'；'.join(factors) or '事件未提供更多原因'}。"
                )
                if exact_findings:
                    summary += (
                        "同时发现的其他异常对象：" if is_test else "当前影响对象："
                    ) + "；".join(exact_findings)
            elif exact_findings:
                summary = f"{prefix}当前异常对象：" + "；".join(exact_findings)
            else:
                summary = f"{prefix}Kubernetes API 检测到对象状态异常"
            boundary = (
                ["模拟告警没有真实触发条件，不能证明调查发现由该告警导致"]
                if is_test
                else ([] if event_items else ["异常对象对应的 Kubernetes Event"])
            )
            if reason == "Unhealthy":
                recommendations = [
                    f"检查 {event_target} 的容器状态和 kubelet 探针记录",
                    "验证健康检查端点是否可访问，以及组件是否存在 CPU 抢占或响应阻塞",
                    "观察 Event 是否继续增长；恢复后重新运行分析",
                ]
            else:
                recommendations = [
                    "优先处理报告列出的具体 Pod、工作负载或 Node",
                    "根据 Warning Event 的 reason 和 message 修复调度、镜像或存储问题",
                    "处理后重新分析，确认对象恢复 Ready 且 Warning Event 不再增长",
                ]
            return RootCauseOutput(
                summary=summary,
                confidence=0.88
                if is_test
                else (0.92 if abnormal_pod_items and event_items else 0.86),
                hypotheses=[
                    {
                        "cause": cause,
                        "confidence": (
                            0.88
                            if is_test
                            else (0.92 if abnormal_pod_items and event_items else 0.86)
                        ),
                        "supporting_evidence_ids": supporting,
                        "contradicting_evidence_ids": [],
                        "missing_evidence": boundary,
                    }
                ],
                recommended_actions=recommendations,
                missing_evidence=boundary,
            )

        if not issues:
            return RootCauseOutput(
                summary=(
                    "真实 Prometheus 指标显示 Kubernetes 集群当前整体健康，未发现可归因的活动故障"
                ),
                confidence=0.9,
                hypotheses=[],
                recommended_actions=[
                    "保持只读监控并在真实告警发生时重新运行分析",
                    "补充 Loki 后可进一步关联 Pod 日志与指标",
                ],
                missing_evidence=([] if log_items else ["当前未接入 Kubernetes 日志数据源"]),
            )

        if log_patterns:
            summary = (
                "主要异常集中在 Kubernetes 存储与控制器组件："
                + "；".join(log_patterns[:3])
                + "。同时指标窗口内检测到"
                + "、".join(issues)
            )
            cause = "CSI/集群控制器异常导致部分工作负载未就绪"
            recommendations = [
                "定位包含 Leader Election 和 API 资源错误的 Pod、控制器及 Namespace",
                "核对 CSI/控制器版本与当前 Kubernetes API 版本的兼容性",
                "查看对应异常 Pod 的 Kubernetes Event，确认等待原因与镜像、挂载或调度事件",
            ]
            missing = ["异常 Pod 与日志来源的精确归属关系", "Kubernetes Event"]
            confidence = 0.84
        else:
            summary = "真实集群指标检测到：" + "；".join(issues)
            cause = "Kubernetes 工作负载或节点健康异常"
            recommendations = [
                "使用 kubectl get pods -A 检查异常 Pod 的状态和所在节点",
                "查看异常工作负载的 Kubernetes Event",
                "接入 Loki 后关联容器启动失败或重启前日志",
            ]
            missing = ["Kubernetes Event", "异常 Pod 容器日志"]
            confidence = 0.78
        return RootCauseOutput(
            summary=summary,
            confidence=confidence,
            hypotheses=[
                {
                    "cause": cause,
                    "confidence": confidence,
                    "supporting_evidence_ids": supporting,
                    "contradicting_evidence_ids": [],
                    "missing_evidence": missing,
                }
            ],
            recommended_actions=recommendations,
            missing_evidence=missing,
        )
