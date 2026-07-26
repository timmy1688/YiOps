import hashlib
import json
import re
from datetime import datetime

from app.agents.domain import EvidenceRecord, QueryTemplate, ToolResult
from app.models import new_id

SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization|token|password|secret)=\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]+"),
)


def redact(text: str) -> str:
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def build_evidence(
    result: ToolResult,
    template: QueryTemplate,
    *,
    service: str,
    tool_execution_id: str,
) -> EvidenceRecord | None:
    if result.status != "completed" or result.result_count == 0:
        return None
    if template.kind == "metric":
        return _metric_evidence(result, template, service, tool_execution_id)
    if template.kind == "object":
        return _object_evidence(result, template, service, tool_execution_id)
    return _log_evidence(result, template, service, tool_execution_id)


def _metric_evidence(
    result: ToolResult,
    template: QueryTemplate,
    service: str,
    tool_execution_id: str,
) -> EvidenceRecord:
    values = result.data.get("values", [])
    if values:
        midpoint = max(1, len(values) // 2)
        baseline_values = values[:midpoint]
        current_values = values[midpoint:]
        baseline = sum(baseline_values) / max(1, len(baseline_values))
        current = sum(current_values) / max(1, len(current_values))
        peak = max(values)
    else:
        baseline = float(result.data.get("baseline", 0))
        current = float(result.data.get("current", 0))
        peak = float(result.data.get("peak", current))
    change = ((current - baseline) / abs(baseline) * 100) if baseline else 0.0
    summary = (
        f"{template.title}: baseline={baseline:.4g}, current={current:.4g}, "
        f"peak={peak:.4g}, change={change:.1f}%"
    )
    observed_at = _parse_datetime(result.data.get("observed_at"))
    payload = {
        "template": template.id,
        "service": service,
        "baseline": baseline,
        "current": current,
        "peak": peak,
    }
    return EvidenceRecord(
        id=new_id("metric"),
        type="metric_anomaly",
        source=result.source,
        title=template.title,
        summary=summary,
        observed_at=observed_at,
        subject={"service": service},
        values={
            "baseline": baseline,
            "current": current,
            "peak": peak,
            "change_percent": round(change, 2),
        },
        quality=0.95 if result.result_count >= 30 else 0.8,
        content_hash=_hash_payload(payload),
        tool_execution_id=tool_execution_id,
    )


def _log_evidence(
    result: ToolResult,
    template: QueryTemplate,
    service: str,
    tool_execution_id: str,
) -> EvidenceRecord:
    samples = [redact(str(sample))[:500] for sample in result.data.get("samples", [])][:5]
    summary = (
        f"{template.title}: {result.result_count} matching events; samples={'; '.join(samples[:2])}"
    )
    payload = {
        "template": template.id,
        "service": service,
        "count": result.result_count,
        "samples": samples,
    }
    return EvidenceRecord(
        id=new_id("log"),
        type="log_pattern",
        source=result.source,
        title=template.title,
        summary=summary,
        observed_at=_parse_datetime(result.data.get("observed_at")),
        subject={"service": service},
        values={"count": result.result_count, "samples": samples},
        quality=0.9 if samples else 0.7,
        content_hash=_hash_payload(payload),
        tool_execution_id=tool_execution_id,
    )


def _object_evidence(
    result: ToolResult,
    template: QueryTemplate,
    service: str,
    tool_execution_id: str,
) -> EvidenceRecord:
    items = result.data.get("items", [])
    if not isinstance(items, list):
        items = []
    items = items[:20]
    descriptions = [
        str(item.get("summary") or item.get("message") or item.get("name") or "")
        for item in items[:5]
        if isinstance(item, dict)
    ]
    summary = f"{template.title}: {result.result_count} items"
    if descriptions:
        summary += "; " + "; ".join(descriptions)
    payload = {
        "template": template.id,
        "service": service,
        "items": items,
    }
    return EvidenceRecord(
        id=new_id("k8s"),
        type=(
            "kubernetes_event" if template.id == "k8s_api_warning_events" else "kubernetes_state"
        ),
        source=result.source,
        title=template.title,
        summary=redact(summary)[:4000],
        observed_at=_parse_datetime(result.data.get("observed_at")),
        subject={"service": service},
        values={"count": result.result_count, "items": items},
        quality=0.98,
        content_hash=_hash_payload(payload),
        tool_execution_id=tool_execution_id,
    )


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
