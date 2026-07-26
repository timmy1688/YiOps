import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.models import AlertEvent, Incident, new_id
from app.schemas import ManualIncidentCreate


async def create_manual_incident(payload: ManualIncidentCreate) -> Incident:
    alert = {
        "alert_name": payload.alert_name,
        "service": payload.service,
        "cluster": payload.cluster,
        "namespace": payload.namespace,
        "instance": payload.instance,
        "severity": payload.severity,
        "status": "firing",
        "started_at": payload.started_at,
        "labels": payload.labels,
        "annotations": payload.annotations,
    }
    return await create_or_aggregate_alert(alert, source="manual")


async def ingest_alertmanager(
    payload: dict[str, Any],
    *,
    default_cluster: str | None = None,
    default_namespace: str | None = None,
) -> list[Incident]:
    incidents: list[Incident] = []
    common_labels = payload.get("commonLabels", {})
    for raw in payload.get("alerts", []):
        labels = {**common_labels, **raw.get("labels", {})}
        annotations = raw.get("annotations", {})
        alert = {
            "external_id": raw.get("fingerprint"),
            "alert_name": labels.get("alertname", "UnknownAlert"),
            "service": (
                labels.get("service") or labels.get("app") or labels.get("job") or "unknown-service"
            ),
            "cluster": labels.get("cluster") or default_cluster,
            "namespace": labels.get("namespace") or default_namespace,
            "instance": labels.get("instance") or labels.get("pod"),
            "severity": labels.get("severity", "warning"),
            "status": raw.get("status", payload.get("status", "firing")),
            "started_at": _parse_datetime(raw.get("startsAt")) or datetime.now(UTC),
            "ended_at": _parse_datetime(raw.get("endsAt")),
            "labels": labels,
            "annotations": annotations,
        }
        incidents.append(await create_or_aggregate_alert(alert, source="alertmanager"))
    return incidents


async def create_or_aggregate_alert(
    alert: dict[str, Any],
    *,
    source: str,
) -> Incident:
    started_at = _ensure_utc(alert["started_at"])
    aggregation_key = _aggregation_key(alert, started_at)
    fingerprint = str(alert.get("external_id") or _fingerprint(alert))
    duplicate = await AlertEvent.get_or_none(
        fingerprint=fingerprint,
        started_at=started_at,
    )
    if duplicate is not None:
        return await Incident.get(id=duplicate.incident_id)

    incident = await Incident.get_or_none(aggregation_key=aggregation_key, status="open")
    if incident is None:
        incident = await Incident.create(
            id=new_id("inc"),
            aggregation_key=aggregation_key,
            title=f"{alert['alert_name']} · {alert['service']}",
            service=str(alert["service"]),
            cluster=alert.get("cluster"),
            namespace=alert.get("namespace"),
            severity=str(alert.get("severity", "warning")),
            status="open",
            started_at=started_at,
            alert_count=1,
        )
    else:
        incident.alert_count += 1
        if _severity_rank(str(alert.get("severity"))) > _severity_rank(incident.severity):
            incident.severity = str(alert["severity"])
        await incident.save(update_fields=["alert_count", "severity", "updated_at"])

    await AlertEvent.create(
        id=new_id("alert"),
        source=source,
        external_id=alert.get("external_id"),
        fingerprint=fingerprint,
        alert_name=str(alert["alert_name"]),
        service=str(alert["service"]),
        cluster=alert.get("cluster"),
        namespace=alert.get("namespace"),
        instance=alert.get("instance"),
        severity=str(alert.get("severity", "warning")),
        status=str(alert.get("status", "firing")),
        started_at=started_at,
        ended_at=alert.get("ended_at"),
        labels=alert.get("labels", {}),
        annotations=alert.get("annotations", {}),
        incident_id=incident.id,
    )
    return incident


def _aggregation_key(alert: dict[str, Any], started_at: datetime) -> str:
    bucket = int(started_at.timestamp() // 600)
    raw = "|".join(
        [
            str(alert.get("cluster") or "-"),
            str(alert.get("namespace") or "-"),
            str(alert.get("service") or "-"),
            str(alert.get("alert_name") or "-"),
            str(bucket),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _fingerprint(alert: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "alert_name": alert.get("alert_name"),
            "service": alert.get("service"),
            "instance": alert.get("instance"),
            "labels": alert.get("labels", {}),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_datetime(value: object) -> datetime | None:
    if not value or str(value).startswith("0001-"):
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _severity_rank(value: str) -> int:
    return {"info": 0, "warning": 1, "critical": 2}.get(value, 1)
