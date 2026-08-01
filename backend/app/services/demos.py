import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import (
    AlertEvent,
    AnalysisRun,
    EvidenceItem,
    Incident,
    Investigation,
    InvestigationEvidence,
    InvestigationHypothesis,
    InvestigationMessage,
    InvestigationStep,
    RootCauseReport,
    ToolExecution,
    new_id,
)

DEMO_CASES: list[dict[str, Any]] = [
    {
        "slug": "crashloop-config",
        "title": "支付服务配置缺失导致 CrashLoop",
        "service": "payment-api",
        "alert": "KubePodCrashLooping",
        "severity": "critical",
        "cause": "新版本引用的 ConfigMap 缺少 DB_URL 环境变量，进程启动失败并持续重启",
        "confidence": 0.96,
        "evidence": [
            ("loki", "启动日志定位配置缺失", "startup failed: missing DB_URL environment variable"),
            (
                "kubernetes",
                "Pod 进入 CrashLoopBackOff",
                "新 ReplicaSet 连续重启，ConfigMap 中不存在 DB_URL 键",
            ),
            ("prometheus", "排除资源瓶颈", "故障窗口 CPU 与内存使用率均低于请求值"),
        ],
    },
    {
        "slug": "db-pool",
        "title": "流量尖峰耗尽数据库连接池",
        "service": "checkout-api",
        "alert": "Http5xxRateHigh",
        "severity": "critical",
        "cause": "数据库连接池达到上限，请求等待连接超时并触发 5xx",
        "confidence": 0.93,
        "evidence": [
            (
                "prometheus",
                "连接池使用率达到 100%",
                "active connections 与 max connections 在故障窗口持续重合",
            ),
            (
                "loki",
                "最近 10 条错误日志命中连接超时",
                "8 条日志包含 pool exhausted 和 connection timeout",
            ),
            (
                "kubernetes",
                "工作负载状态正常",
                "全部 checkout-api Pod 保持 Ready，未发生重启或驱逐",
            ),
        ],
    },
    {
        "slug": "disk-pressure",
        "title": "节点磁盘耗尽驱逐业务 Pod",
        "service": "catalog-api",
        "alert": "KubePodEvicted",
        "severity": "warning",
        "cause": "容器日志填满节点临时盘，触发 DiskPressure 并驱逐 catalog-api Pod",
        "confidence": 0.95,
        "evidence": [
            (
                "kubernetes",
                "节点进入 DiskPressure",
                "Node condition DiskPressure=True，业务 Pod 原因为 Evicted",
            ),
            ("loki", "日志写入失败", "驱逐前持续出现 no space left on device"),
            (
                "prometheus",
                "节点磁盘可用率归零",
                "node filesystem available ratio 在故障窗口降至 1% 以下",
            ),
        ],
    },
]


async def import_official_demos(tenant_id: str) -> dict[str, Any]:
    created: list[str] = []
    existing: list[str] = []
    investigation_ids: list[str] = []
    now = datetime.now(UTC)
    for offset, case in enumerate(DEMO_CASES):
        key = f"yiops-demo:{tenant_id}:{case['slug']}"
        incident = await Incident.get_or_none(tenant_id=tenant_id, aggregation_key=key)
        if incident is not None:
            existing.append(incident.id)
            investigation = await Investigation.filter(incident_id=incident.id).first()
            if investigation:
                investigation_ids.append(investigation.id)
            continue

        started_at = now - timedelta(minutes=42 - offset * 7)
        incident = await Incident.create(
            id=new_id("inc"),
            tenant_id=tenant_id,
            aggregation_key=key,
            title=case["title"],
            service=case["service"],
            cluster="demo-production",
            namespace="ecommerce",
            severity=case["severity"],
            status="resolved",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=12),
            alert_count=3,
        )
        await AlertEvent.create(
            id=new_id("alert"),
            tenant_id=tenant_id,
            source="yiops-demo",
            external_id=case["slug"],
            fingerprint=hashlib.sha256(key.encode()).hexdigest(),
            alert_name=case["alert"],
            service=case["service"],
            cluster="demo-production",
            namespace="ecommerce",
            severity=case["severity"],
            status="resolved",
            started_at=started_at,
            ended_at=started_at + timedelta(minutes=12),
            labels={"yiops_demo": "true", "service": case["service"]},
            annotations={"summary": case["title"]},
            incident_id=incident.id,
        )
        run = await AnalysisRun.create(
            id=new_id("run"),
            incident_id=incident.id,
            status="completed",
            current_step="save",
            progress=1,
            model_name="yiops-demo-agent",
            input_tokens=2860,
            output_tokens=420,
            started_at=started_at + timedelta(minutes=1),
            completed_at=started_at + timedelta(minutes=4),
        )
        evidence_ids: list[str] = []
        for source, title, summary in case["evidence"]:
            execution = await ToolExecution.create(
                id=new_id("tool"),
                analysis_run_id=run.id,
                source=source,
                query_pack="official_demo",
                template_id=f"demo_{case['slug']}_{source}",
                parameters={"service": case["service"], "window": "30m"},
                status="completed",
                duration_ms=120 + len(evidence_ids) * 55,
                result_count=1,
                result_summary={"summary": summary},
            )
            evidence_id = new_id("evidence")
            evidence_ids.append(evidence_id)
            await EvidenceItem.create(
                id=evidence_id,
                analysis_run_id=run.id,
                tool_execution_id=execution.id,
                type="demo_observation",
                source=source,
                title=title,
                summary=summary,
                observed_at=started_at + timedelta(minutes=2),
                subject={"service": case["service"]},
                values={"synthetic": True},
                quality=0.95,
                content_hash=hashlib.sha256(f"{key}:{source}:{summary}".encode()).hexdigest(),
            )
        await RootCauseReport.create(
            id=new_id("report"),
            analysis_run_id=run.id,
            status="completed",
            summary=case["cause"],
            confidence=case["confidence"],
            hypotheses=[
                {
                    "cause": case["cause"],
                    "confidence": case["confidence"],
                    "supporting_evidence_ids": evidence_ids[:2],
                    "contradicting_evidence_ids": [],
                    "missing_evidence": [],
                }
            ],
            recommended_actions=["先执行可回滚的止损动作", "补充对应指标和日志告警"],
            missing_evidence=[],
        )
        investigation = await _create_demo_investigation(
            tenant_id, incident, run, case, evidence_ids, started_at
        )
        created.append(incident.id)
        investigation_ids.append(investigation.id)
    return {
        "created_incident_ids": created,
        "existing_incident_ids": existing,
        "investigation_ids": investigation_ids,
        "demo_count": len(DEMO_CASES),
    }


async def remove_official_demos(tenant_id: str) -> dict[str, int]:
    prefix = f"yiops-demo:{tenant_id}:"
    query = Incident.filter(tenant_id=tenant_id, aggregation_key__startswith=prefix)
    removed = await query.count()
    await query.delete()
    return {"removed_incidents": removed}


async def _create_demo_investigation(
    tenant_id: str,
    incident: Incident,
    run: AnalysisRun,
    case: dict[str, Any],
    evidence_ids: list[str],
    started_at: datetime,
) -> Investigation:
    investigation = await Investigation.create(
        id=new_id("inv"),
        tenant_id=tenant_id,
        incident_id=incident.id,
        title=case["title"],
        status="completed",
        current_step="形成结论",
        progress=1,
        model_name="yiops-demo-agent",
        summary=case["cause"],
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        tool_count=len(case["evidence"]),
        started_at=run.started_at,
        completed_at=run.completed_at,
    )
    await InvestigationMessage.create(
        id=new_id("msg"),
        investigation_id=investigation.id,
        role="user",
        content=f"请分析「{case['title']}」并用多源证据验证根因。",
    )
    await InvestigationMessage.create(
        id=new_id("msg"),
        investigation_id=investigation.id,
        role="assistant",
        content=(
            f"**根因结论（置信度 {case['confidence']:.0%}）**\n\n"
            f"{case['cause']}\n\n所有结论均可追溯到已保存的合成证据。"
        ),
        model_name="yiops-demo-agent",
        tool_calls=[],
    )
    investigation_evidence_ids: list[str] = []
    for sequence, (source, title, summary) in enumerate(case["evidence"], start=1):
        step = await InvestigationStep.create(
            id=new_id("step"),
            investigation_id=investigation.id,
            sequence=sequence,
            name=f"query_{source}",
            source=source,
            status="completed",
            description=f"查询 {source} 并验证候选根因",
            parameters={"service": case["service"]},
            result_count=1,
            duration_ms=120 + sequence * 55,
            completed_at=started_at + timedelta(minutes=sequence),
        )
        inv_evidence_id = new_id("inv_ev")
        investigation_evidence_ids.append(inv_evidence_id)
        await InvestigationEvidence.create(
            id=inv_evidence_id,
            investigation_id=investigation.id,
            step_id=step.id,
            source=source,
            title=title,
            summary=summary,
            observed_at=started_at + timedelta(minutes=sequence),
            subject={"service": case["service"]},
            values={"synthetic": True, "analysis_evidence_id": evidence_ids[sequence - 1]},
            quality=0.95,
        )
    await InvestigationHypothesis.create(
        id=new_id("hyp"),
        investigation_id=investigation.id,
        cause=case["cause"],
        confidence=case["confidence"],
        status="confirmed",
        supporting_evidence_ids=investigation_evidence_ids[:2],
        contradicting_evidence_ids=[],
        missing_evidence=[],
    )
    return investigation
