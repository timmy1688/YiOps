import asyncio
import ssl
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

from app.agents.domain import QueryTemplate, ToolResult
from app.config import Settings
from app.models import DatasourceConfig
from app.security.credentials import CredentialVault


class DatasourceClient:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self.vault = CredentialVault()

    async def execute(
        self,
        template: QueryTemplate,
        *,
        service: str,
        start: datetime,
        end: datetime,
        cluster: str | None = None,
        namespace: str | None = None,
    ) -> ToolResult:
        started = monotonic()
        try:
            if self.settings.datasource_mock_mode:
                result = await self._mock_execute(template, service, end)
            else:
                datasource = await self._get_datasource(template.source, cluster)
                if datasource is None:
                    raise RuntimeError(f"No enabled {template.source} datasource configured")
                if template.source == "prometheus":
                    result = await self._query_prometheus(
                        datasource,
                        template,
                        service,
                        start,
                        end,
                    )
                elif template.source == "loki":
                    result = await self._query_loki(
                        datasource,
                        template,
                        service,
                        start,
                        end,
                        namespace,
                    )
                elif template.source == "kubernetes":
                    result = await self._query_kubernetes(
                        datasource,
                        template,
                        service=service,
                        namespace=namespace,
                        start=start,
                        end=end,
                    )
                else:
                    result = await self._query_elasticsearch(
                        datasource,
                        template,
                        service,
                        start,
                        end,
                    )
            result.duration_ms = int((monotonic() - started) * 1000)
            return result
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            return ToolResult(
                source=template.source,
                query_pack=template.query_pack,
                template_id=template.id,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_code=type(exc).__name__,
                data={"message": str(exc)[:500]},
            )

    async def test_connection(self, datasource: DatasourceConfig) -> tuple[bool, str]:
        if self.settings.datasource_mock_mode:
            return True, "mock mode"
        path = {
            "prometheus": "/-/healthy",
            "loki": "/ready",
            "elasticsearch": "/",
            "kubernetes": "/version",
        }[datasource.type]
        try:
            headers: dict[str, str] = {}
            verify: bool | ssl.SSLContext = True
            if datasource.type == "kubernetes":
                secrets = self.vault.decrypt(datasource.secret_ref)
                if secrets.get("token"):
                    headers["Authorization"] = f"Bearer {secrets['token']}"
                verify = self._kubernetes_verify(datasource, secrets)
            async with httpx.AsyncClient(
                timeout=self.settings.datasource_timeout_seconds,
                verify=verify,
                headers=headers,
                trust_env=False,
            ) as client:
                response = await client.get(f"{datasource.base_url.rstrip('/')}{path}")
                response.raise_for_status()
            if datasource.type == "kubernetes":
                version = response.json().get("gitVersion", "unknown")
                return True, f"connected ({version})"
            return True, "connected"
        except httpx.HTTPError as exc:
            return False, str(exc)[:500]

    async def _get_datasource(
        self,
        source: str,
        cluster: str | None = None,
    ) -> DatasourceConfig | None:
        items = await DatasourceConfig.filter(type=source, enabled=True).order_by("created_at")
        if not items:
            return None
        if source == "kubernetes" and cluster:
            for item in items:
                if str(item.settings.get("cluster_id", "")) == cluster:
                    return item
        return items[0] if len(items) == 1 or source != "kubernetes" else None

    async def _query_prometheus(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        query = template.query.replace("{service}", service.replace('"', ""))
        params = {
            "query": query,
            "start": int(start.replace(tzinfo=UTC).timestamp()),
            "end": int(end.replace(tzinfo=UTC).timestamp()),
            "step": "30s",
        }
        async with httpx.AsyncClient(
            timeout=self.settings.datasource_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{datasource.base_url.rstrip('/')}/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        series = payload.get("data", {}).get("result", [])
        values = [
            float(point[1])
            for item in series
            for point in item.get("values", [])
            if len(point) == 2
        ]
        return ToolResult(
            source="prometheus",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(values),
            data={"values": values[-600:]},
        )

    async def _query_loki(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
        namespace: str | None,
    ) -> ToolResult:
        escaped_namespace = (
            namespace.replace("\\", "\\\\").replace('"', '\\"') if namespace else None
        )
        namespace_selector = (
            f'namespace="{escaped_namespace}"' if escaped_namespace else 'namespace=~".+"'
        )
        query = (
            template.query.replace("{service}", service.replace('"', ""))
            .replace('namespace=~"{namespace}"', namespace_selector)
        )
        params = {
            "query": query,
            "start": int(start.replace(tzinfo=UTC).timestamp() * 1_000_000_000),
            "end": int(end.replace(tzinfo=UTC).timestamp() * 1_000_000_000),
            "limit": self.settings.max_log_samples,
            "direction": "backward",
        }
        async with httpx.AsyncClient(
            timeout=self.settings.datasource_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{datasource.base_url.rstrip('/')}/loki/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        streams = payload.get("data", {}).get("result", [])
        samples = [
            value[1][:1000]
            for stream in streams
            for value in stream.get("values", [])
            if len(value) == 2
        ][: self.settings.max_log_samples]
        return ToolResult(
            source="loki",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(samples),
            data={"samples": samples},
        )

    async def _query_elasticsearch(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        index_alias = str(datasource.settings.get("index_alias", "logs-*"))
        body: dict[str, Any] = {
            "size": self.settings.max_log_samples,
            "_source": ["@timestamp", "message", "service.name", "log.level"],
            "sort": [{"@timestamp": "desc"}],
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"service.name": service}},
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": start.isoformat(),
                                    "lte": end.isoformat(),
                                }
                            }
                        },
                    ],
                    "must": [
                        {
                            "query_string": {
                                "query": "log.level:(ERROR OR FATAL) OR message:*Exception*"
                            }
                        }
                    ],
                }
            },
        }
        async with httpx.AsyncClient(
            timeout=self.settings.datasource_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{datasource.base_url.rstrip('/')}/{index_alias}/_search",
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        hits = payload.get("hits", {}).get("hits", [])
        samples = [str(hit.get("_source", {}).get("message", ""))[:1000] for hit in hits]
        return ToolResult(
            source="elasticsearch",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(samples),
            data={"samples": samples},
        )

    async def _query_kubernetes(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        *,
        service: str,
        namespace: str | None,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        secrets = self.vault.decrypt(datasource.secret_ref)
        token = secrets.get("token")
        if not token:
            raise RuntimeError("Kubernetes datasource has no ServiceAccount token")
        headers = {"Authorization": f"Bearer {token}"}
        verify = self._kubernetes_verify(datasource, secrets)
        configured_namespace = str(datasource.settings.get("default_namespace", "")).strip()
        scope = (namespace or configured_namespace).strip()
        if service == "kubernetes-cluster" or scope.lower() in {"", "all", "*", "-"}:
            scope = ""
        async with httpx.AsyncClient(
            base_url=datasource.base_url.rstrip("/"),
            timeout=self.settings.datasource_timeout_seconds,
            headers=headers,
            verify=verify,
            trust_env=False,
        ) as client:
            if template.id == "k8s_api_abnormal_pods":
                items = await self._kubernetes_abnormal_pods(client, scope)
            elif template.id == "k8s_api_workload_status":
                items = await self._kubernetes_unhealthy_workloads(client, scope)
            elif template.id == "k8s_api_node_conditions":
                items = await self._kubernetes_unhealthy_nodes(client)
            elif template.id == "k8s_api_warning_events":
                items = await self._kubernetes_warning_events(client, scope, start, end)
            else:
                raise ValueError(f"Unsupported Kubernetes template: {template.id}")
        return ToolResult(
            source="kubernetes",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(items),
            data={"items": items[:30], "observed_at": datetime.now(UTC).isoformat()},
        )

    async def _kubernetes_abnormal_pods(
        self,
        client: httpx.AsyncClient,
        namespace: str,
    ) -> list[dict[str, Any]]:
        path = f"/api/v1/namespaces/{namespace}/pods" if namespace else "/api/v1/pods"
        payload = await self._kubernetes_get(client, path, params={"limit": 500})
        findings: list[dict[str, Any]] = []
        for pod in payload.get("items", []):
            metadata = pod.get("metadata", {})
            status = pod.get("status", {})
            phase = str(status.get("phase", "Unknown"))
            containers: list[dict[str, Any]] = []
            waiting_reasons: list[str] = []
            for container in status.get("containerStatuses", []) or []:
                state = container.get("state", {})
                waiting = state.get("waiting") or {}
                terminated = state.get("terminated") or {}
                reason = waiting.get("reason") or terminated.get("reason")
                if waiting.get("reason"):
                    waiting_reasons.append(str(waiting["reason"]))
                containers.append(
                    {
                        "name": container.get("name"),
                        "ready": bool(container.get("ready")),
                        "restart_count": int(container.get("restartCount", 0)),
                        "reason": reason,
                    }
                )
            ready = any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in status.get("conditions", []) or []
            )
            if phase in {"Succeeded"} or (phase == "Running" and ready and not waiting_reasons):
                continue
            owners = metadata.get("ownerReferences", []) or []
            owner = owners[0] if owners else {}
            reason = (
                ", ".join(dict.fromkeys(waiting_reasons))
                or status.get("reason")
                or self._pod_condition_reason(status)
                or phase
            )
            name = str(metadata.get("name", "unknown"))
            pod_namespace = str(metadata.get("namespace", "default"))
            findings.append(
                {
                    "kind": "Pod",
                    "namespace": pod_namespace,
                    "name": name,
                    "phase": phase,
                    "reason": reason,
                    "message": str(status.get("message") or "")[:500],
                    "node": pod.get("spec", {}).get("nodeName"),
                    "owner": (f"{owner.get('kind')}/{owner.get('name')}" if owner else None),
                    "containers": containers,
                    "summary": (
                        f"{pod_namespace}/{name}: phase={phase}, reason={reason}, "
                        f"owner={owner.get('kind', '-')}/{owner.get('name', '-')}"
                    ),
                }
            )
        return findings

    async def _kubernetes_unhealthy_workloads(
        self,
        client: httpx.AsyncClient,
        namespace: str,
    ) -> list[dict[str, Any]]:
        resources = (
            ("Deployment", "deployments"),
            ("StatefulSet", "statefulsets"),
            ("DaemonSet", "daemonsets"),
        )
        findings: list[dict[str, Any]] = []
        for kind, plural in resources:
            path = (
                f"/apis/apps/v1/namespaces/{namespace}/{plural}"
                if namespace
                else f"/apis/apps/v1/{plural}"
            )
            payload = await self._kubernetes_get(client, path, params={"limit": 500})
            for workload in payload.get("items", []):
                metadata = workload.get("metadata", {})
                spec = workload.get("spec", {})
                status = workload.get("status", {})
                desired, ready = self._workload_replicas(kind, spec, status)
                if ready >= desired:
                    continue
                name = str(metadata.get("name", "unknown"))
                item_namespace = str(metadata.get("namespace", "default"))
                findings.append(
                    {
                        "kind": kind,
                        "namespace": item_namespace,
                        "name": name,
                        "desired": desired,
                        "ready": ready,
                        "unavailable": max(0, desired - ready),
                        "summary": (f"{item_namespace}/{kind}/{name}: ready={ready}/{desired}"),
                    }
                )
        return findings

    async def _kubernetes_unhealthy_nodes(
        self,
        client: httpx.AsyncClient,
    ) -> list[dict[str, Any]]:
        payload = await self._kubernetes_get(client, "/api/v1/nodes", params={"limit": 500})
        findings: list[dict[str, Any]] = []
        for node in payload.get("items", []):
            metadata = node.get("metadata", {})
            conditions = node.get("status", {}).get("conditions", []) or []
            problems = [
                {
                    "type": condition.get("type"),
                    "status": condition.get("status"),
                    "reason": condition.get("reason"),
                    "message": str(condition.get("message") or "")[:500],
                }
                for condition in conditions
                if (condition.get("type") == "Ready" and condition.get("status") != "True")
                or (
                    condition.get("type")
                    in {"MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"}
                    and condition.get("status") == "True"
                )
            ]
            if not problems:
                continue
            name = str(metadata.get("name", "unknown"))
            findings.append(
                {
                    "kind": "Node",
                    "name": name,
                    "conditions": problems,
                    "summary": (
                        f"Node/{name}: "
                        + ", ".join(
                            f"{item['type']}={item['status']}({item['reason']})"
                            for item in problems
                        )
                    ),
                }
            )
        return findings

    async def _kubernetes_warning_events(
        self,
        client: httpx.AsyncClient,
        namespace: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        path = f"/api/v1/namespaces/{namespace}/events" if namespace else "/api/v1/events"
        payload = await self._kubernetes_get(client, path, params={"limit": 500})
        findings: list[dict[str, Any]] = []
        for event in payload.get("items", []):
            if event.get("type") != "Warning":
                continue
            event_time = self._parse_kubernetes_time(
                event.get("eventTime")
                or event.get("lastTimestamp")
                or event.get("metadata", {}).get("creationTimestamp")
            )
            if event_time and not (start.astimezone(UTC) <= event_time <= end.astimezone(UTC)):
                continue
            involved = event.get("involvedObject", {})
            metadata = event.get("metadata", {})
            name = str(involved.get("name", "unknown"))
            item_namespace = str(involved.get("namespace") or metadata.get("namespace") or "-")
            reason = str(event.get("reason", "Warning"))
            message = str(event.get("message") or "")[:800]
            findings.append(
                {
                    "kind": "Event",
                    "namespace": item_namespace,
                    "name": name,
                    "object_kind": involved.get("kind"),
                    "reason": reason,
                    "message": message,
                    "count": int(event.get("count", 1) or 1),
                    "observed_at": event_time.isoformat() if event_time else None,
                    "summary": (
                        f"{item_namespace}/{involved.get('kind', 'Object')}/{name}: "
                        f"{reason} - {message}"
                    ),
                }
            )
        findings.sort(key=lambda item: str(item.get("observed_at") or ""), reverse=True)
        return findings[:30]

    @staticmethod
    async def _kubernetes_get(
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _pod_condition_reason(status: dict[str, Any]) -> str | None:
        for condition in status.get("conditions", []) or []:
            if condition.get("status") != "True" and condition.get("reason"):
                return str(condition["reason"])
        return None

    @staticmethod
    def _workload_replicas(
        kind: str,
        spec: dict[str, Any],
        status: dict[str, Any],
    ) -> tuple[int, int]:
        if kind == "DaemonSet":
            return (
                int(status.get("desiredNumberScheduled", 0) or 0),
                int(status.get("numberReady", 0) or 0),
            )
        return (
            int(spec.get("replicas", 1) or 0),
            int(status.get("readyReplicas", 0) or 0),
        )

    @staticmethod
    def _parse_kubernetes_time(value: object) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None

    @staticmethod
    def _kubernetes_verify(
        datasource: DatasourceConfig,
        secrets: dict[str, str],
    ) -> bool | ssl.SSLContext:
        if not bool(datasource.settings.get("verify_ssl", True)):
            return False
        ca_cert = secrets.get("ca_cert")
        if ca_cert:
            return ssl.create_default_context(cadata=ca_cert)
        return True

    async def _mock_execute(
        self,
        template: QueryTemplate,
        service: str,
        observed_at: datetime,
    ) -> ToolResult:
        await asyncio.sleep(0.02)
        metric_values = {
            "http_request_rate": (920.0, 980.0, 1050.0),
            "http_error_rate": (0.004, 0.182, 0.211),
            "http_p99_latency": (0.24, 2.8, 3.4),
            "cpu_usage": (0.36, 0.41, 0.48),
            "memory_usage": (820_000_000.0, 850_000_000.0, 880_000_000.0),
            "instance_up": (6.0, 6.0, 6.0),
            "dependency_error_rate": (0.002, 0.008, 0.01),
            "dependency_latency": (0.08, 0.11, 0.14),
            "db_pool_active": (18.0, 50.0, 50.0),
        }
        if template.kind == "metric":
            baseline, current, peak = metric_values.get(template.id, (1.0, 1.0, 1.0))
            return ToolResult(
                source=template.source,
                query_pack=template.query_pack,
                template_id=template.id,
                status="completed",
                result_count=120,
                data={
                    "baseline": baseline,
                    "current": current,
                    "peak": peak,
                    "observed_at": observed_at.isoformat(),
                    "service": service,
                },
            )
        samples = (
            [
                "Timeout waiting for database connection from pool",
                "ConnectionPoolTimeout: pool limit reached",
            ]
            if template.id == "db_pool_timeout_logs"
            else [
                "ERROR request failed: Timeout waiting for database connection",
                "DatabaseException: connection acquisition timeout",
            ]
        )
        return ToolResult(
            source=template.source,
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=1264 if "error" in template.id or "timeout" in template.id else 12,
            data={
                "samples": samples,
                "observed_at": observed_at.isoformat(),
                "service": service,
            },
        )
