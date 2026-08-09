import asyncio
import re
import ssl
import tempfile
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

from app.agents.domain import QueryTemplate, ToolResult
from app.analysis.evidence import redact
from app.config import Settings
from app.connectors.registry import registry
from app.models import DatasourceConfig
from app.security.credentials import CredentialVault
from app.security.tenant import tenant_filter


class DatasourceGateway:
    def __init__(self, settings: Settings) -> None:
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
                    result = await self._query_prometheus(datasource, template, service, start, end)
                elif template.source == "loki":
                    result = await self._query_loki(
                        datasource, template, service, start, end, namespace
                    )
                elif template.source == "tempo":
                    result = await self._query_tempo(datasource, template, service, start, end)
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
                        datasource, template, service, start, end
                    )
            result.duration_ms = int((monotonic() - started) * 1000)
            return result
        except (httpx.HTTPError, RuntimeError, ssl.SSLError, ValueError) as exc:
            return ToolResult(
                source=template.source,
                query_pack=template.query_pack,
                template_id=template.id,
                status="failed",
                duration_ms=int((monotonic() - started) * 1000),
                error_code=type(exc).__name__,
                data={"message": str(exc)[:500]},
            )

    async def query_loki_logs(
        self,
        *,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> ToolResult:
        started = monotonic()
        query = query.strip()
        if not query.startswith("{") or "}" not in query or len(query) > 1000:
            raise ValueError("LogQL 必须以日志流选择器开头，且长度不能超过 1000 字符")
        limit = min(max(limit, 1), 50)
        if self.settings.datasource_mock_mode:
            entries = [
                {
                    "timestamp": end.isoformat(),
                    "labels": {"service": "mock-service"},
                    "line": "mock log entry",
                },
                {
                    "timestamp": start.isoformat(),
                    "labels": {"service": "mock-service"},
                    "line": "mock previous log entry",
                },
            ][:limit]
        else:
            datasource = await self._required_datasource("loki")
            payload = await self._native_loki(
                datasource, query=query, start=start, end=end, limit=limit
            )
            entries = self._loki_entries(payload, limit)
        return ToolResult(
            source="loki",
            query_pack="chat",
            template_id="chat_loki_logs",
            status="completed",
            result_count=len(entries),
            data={"query": query, "entries": entries},
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def query_prometheus_range(
        self,
        *,
        query: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> ToolResult:
        started = monotonic()
        query = query.strip()
        if not query or len(query) > 1000:
            raise ValueError("PromQL 不能为空且长度不能超过 1000 字符")
        result_type: str | None
        series: list[dict[str, Any]]
        if self.settings.datasource_mock_mode:
            result_type, series = "matrix", [{"metric": {}, "values": []}]
        else:
            datasource = await self._required_datasource("prometheus")
            payload = await self._native_prometheus(
                datasource,
                query=query,
                start=start,
                end=end,
                step_seconds=min(max(step_seconds, 15), 300),
            )
            result_type, series = self._prometheus_series(payload)
        return ToolResult(
            source="prometheus",
            query_pack="chat",
            template_id="chat_prometheus_range",
            status="completed",
            result_count=len(series),
            data={"query": query, "result_type": result_type, "series": series[:20]},
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def search_tempo_traces(
        self,
        *,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> ToolResult:
        started = monotonic()
        query = query.strip()
        if not query or len(query) > 2000:
            raise ValueError("TraceQL 不能为空且长度不能超过 2000 字符")
        limit = min(max(limit, 1), 50)
        if self.settings.datasource_mock_mode:
            traces = [
                {
                    "trace_id": "0123456789abcdef0123456789abcdef",
                    "root_service_name": "mock-service",
                    "root_trace_name": "GET /api/mock",
                    "start_time": end.isoformat(),
                    "duration_ms": 428,
                    "matched_spans": 1,
                }
            ][:limit]
            metrics: dict[str, Any] = {}
        else:
            datasource = await self._required_datasource("tempo")
            traces, metrics = await self._tempo_search(
                datasource, query=query, start=start, end=end, limit=limit
            )
        return ToolResult(
            source="tempo",
            query_pack="chat",
            template_id="chat_tempo_search",
            status="completed",
            result_count=len(traces),
            data={"query": query, "traces": traces, "metrics": metrics},
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def get_tempo_trace(
        self,
        *,
        trace_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> ToolResult:
        started = monotonic()
        trace_id = trace_id.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16,32}", trace_id):
            raise ValueError("Tempo trace ID 必须是 16-32 位十六进制字符串")
        if self.settings.datasource_mock_mode:
            spans: list[dict[str, Any]] = [
                {
                    "span_id": "0123456789abcdef",
                    "parent_span_id": None,
                    "service_name": "mock-service",
                    "name": "GET /api/mock",
                    "start_time": (end or datetime.now(UTC)).isoformat(),
                    "duration_ms": 428.0,
                    "status": "STATUS_CODE_ERROR",
                    "status_message": "mock upstream timeout",
                    "attributes": {"http.response.status_code": 504},
                    "events": [],
                }
            ]
            total_spans = len(spans)
            summary = None
        else:
            datasource = await self._required_datasource("tempo")
            params = (
                {"start": int(start.timestamp()), "end": int(end.timestamp())}
                if start is not None and end is not None
                else None
            )
            payload = await self._request_json(
                datasource,
                "GET",
                f"/api/v2/traces/{trace_id}",
                params=params,
            )
            spans, total_spans = self._tempo_spans(payload, limit=50)
            summary = self._payload_text(payload)
        data: dict[str, Any] = {
            "trace_id": trace_id,
            "spans": spans,
            "truncated": total_spans > len(spans),
        }
        if summary and not spans:
            data["summary"] = redact(summary)[:4000]
        return ToolResult(
            source="tempo",
            query_pack="chat",
            template_id="chat_tempo_trace",
            status="completed",
            result_count=total_spans,
            data=data,
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def query_elasticsearch_logs(
        self,
        *,
        query: str,
        service: str | None,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> ToolResult:
        started = monotonic()
        query = query.strip() or "*"
        if len(query) > 500:
            raise ValueError("日志搜索条件不能超过 500 字符")
        limit = min(max(limit, 1), 50)
        if self.settings.datasource_mock_mode:
            entries: list[dict[str, Any]] = []
        else:
            datasource = await self._required_datasource("elasticsearch")
            payload = await self._native_elasticsearch(
                datasource,
                query=self._elastic_query(query, service),
                start=start,
                end=end,
                limit=limit,
            )
            entries = self._elasticsearch_entries(payload, limit)
        return ToolResult(
            source="elasticsearch",
            query_pack="chat",
            template_id="chat_elasticsearch_logs",
            status="completed",
            result_count=len(entries),
            data={"query": query, "entries": entries},
            duration_ms=int((monotonic() - started) * 1000),
        )

    async def inspect_kubernetes(
        self,
        *,
        inspection: str,
        cluster: str | None,
        namespace: str | None,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        template_ids = {
            "abnormal_pods": "k8s_api_abnormal_pods",
            "unhealthy_workloads": "k8s_api_workload_status",
            "unhealthy_nodes": "k8s_api_node_conditions",
            "warning_events": "k8s_api_warning_events",
        }
        template_id = template_ids.get(inspection)
        if template_id is None:
            raise ValueError("不支持的 Kubernetes 检查类型")
        return await self.execute(
            QueryTemplate(
                id=template_id,
                query_pack="chat",
                source="kubernetes",
                query=inspection,
                kind="object",
                title=f"Kubernetes {inspection}",
            ),
            service="kubernetes-cluster",
            cluster=cluster,
            namespace=namespace,
            start=start,
            end=end,
        )

    async def test_connection(self, datasource: DatasourceConfig) -> tuple[bool, str]:
        if self.settings.datasource_mock_mode:
            return True, "mock mode"
        try:
            payload = await self._request_json(
                datasource,
                "GET",
                registry.get(datasource.type).health_path,
            )
            if datasource.type == "kubernetes" and isinstance(payload, dict):
                return True, f"connected ({payload.get('gitVersion', 'unknown')})"
            return True, "connected"
        except (httpx.HTTPError, RuntimeError, ssl.SSLError, ValueError) as exc:
            return False, str(exc)[:500]

    async def _required_datasource(self, source: str) -> DatasourceConfig:
        datasource = await self._get_datasource(source)
        if datasource is None:
            raise RuntimeError(f"未配置已启用的 {source} 数据源")
        return datasource

    async def _get_datasource(
        self,
        source: str,
        cluster: str | None = None,
    ) -> DatasourceConfig | None:
        items = await DatasourceConfig.filter(
            type=source,
            enabled=True,
            **tenant_filter(),
        ).order_by("created_at")
        if not items:
            return None
        if source == "kubernetes" and cluster:
            for item in items:
                if str(item.settings.get("cluster_id", "")) == cluster:
                    return item
        return items[0] if len(items) == 1 or source != "kubernetes" else None

    async def _native_prometheus(
        self,
        datasource: DatasourceConfig,
        *,
        query: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> Any:
        return await self._request_json(
            datasource,
            "GET",
            "/api/v1/query_range",
            params={
                "query": query,
                "start": int(start.astimezone(UTC).timestamp()),
                "end": int(end.astimezone(UTC).timestamp()),
                "step": step_seconds,
            },
        )

    async def _native_loki(
        self,
        datasource: DatasourceConfig,
        *,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> Any:
        return await self._request_json(
            datasource,
            "GET",
            "/loki/api/v1/query_range",
            params={
                "query": query,
                "start": int(start.astimezone(UTC).timestamp() * 1_000_000_000),
                "end": int(end.astimezone(UTC).timestamp() * 1_000_000_000),
                "limit": limit,
                "direction": "backward",
            },
        )

    async def _native_elasticsearch(
        self,
        datasource: DatasourceConfig,
        *,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> Any:
        body = {
            "size": limit,
            "_source": ["@timestamp", "message", "service.name", "log.level"],
            "sort": [{"@timestamp": "desc"}],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "range": {
                                "@timestamp": {
                                    "gte": start.astimezone(UTC).isoformat(),
                                    "lte": end.astimezone(UTC).isoformat(),
                                }
                            }
                        }
                    ],
                    "must": [{"simple_query_string": {"query": query}}],
                }
            },
        }
        index = str(datasource.settings.get("index_alias", "logs-*")).strip() or "logs-*"
        return await self._request_json(
            datasource,
            "POST",
            f"/{index}/_search",
            json=body,
        )

    async def _query_prometheus(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        query = template.query.replace("{service}", service.replace('"', ""))
        payload = await self._native_prometheus(
            datasource, query=query, start=start, end=end, step_seconds=30
        )
        _, series = self._prometheus_series(payload)
        values = [
            float(point[1])
            for item in series
            for point in item.get("values", [])
            if isinstance(point, list) and len(point) == 2 and self._is_number(point[1])
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
        selector = f'namespace="{escaped_namespace}"' if escaped_namespace else 'namespace=~".+"'
        query = template.query.replace("{service}", service.replace('"', "")).replace(
            'namespace=~"{namespace}"', selector
        )
        payload = await self._native_loki(
            datasource,
            query=query,
            start=start,
            end=end,
            limit=self.settings.max_log_samples,
        )
        entries = self._loki_entries(payload, self.settings.max_log_samples)
        samples = [str(item.get("line", ""))[:1000] for item in entries]
        return ToolResult(
            source="loki",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(samples),
            data={"samples": samples},
        )

    async def _query_tempo(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        escaped_service = service.replace("\\", "\\\\").replace('"', '\\"')
        query = template.query.replace("{service}", escaped_service)
        traces, metrics = await self._tempo_search(
            datasource, query=query, start=start, end=end, limit=20
        )
        return ToolResult(
            source="tempo",
            query_pack=template.query_pack,
            template_id=template.id,
            status="completed",
            result_count=len(traces),
            data={
                "query": query,
                "traces": traces,
                "metrics": metrics,
                "observed_at": traces[0].get("start_time") if traces else end.isoformat(),
            },
        )

    async def _tempo_search(
        self,
        datasource: DatasourceConfig,
        *,
        query: str,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        payload = await self._request_json(
            datasource,
            "GET",
            "/api/search",
            params={
                "q": query,
                "limit": limit,
                "start": int(start.astimezone(UTC).timestamp()),
                "end": int(end.astimezone(UTC).timestamp()),
            },
        )
        root = self._unwrap_payload(payload)
        raw_traces = root.get("traces", []) if isinstance(root, dict) else []
        if not isinstance(raw_traces, list):
            raw_traces = []
        traces = [self._tempo_trace_summary(item) for item in raw_traces[:limit]]
        metrics = root.get("metrics", {}) if isinstance(root, dict) else {}
        return traces, metrics if isinstance(metrics, dict) else {}

    async def _query_elasticsearch(
        self,
        datasource: DatasourceConfig,
        template: QueryTemplate,
        service: str,
        start: datetime,
        end: datetime,
    ) -> ToolResult:
        payload = await self._native_elasticsearch(
            datasource,
            query=self._elastic_query("log.level:(ERROR OR FATAL) OR message:*Exception*", service),
            start=start,
            end=end,
            limit=self.settings.max_log_samples,
        )
        entries = self._elasticsearch_entries(payload, self.settings.max_log_samples)
        samples = [str(item.get("message", ""))[:1000] for item in entries]
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
        configured = str(datasource.settings.get("default_namespace", "")).strip()
        scope = (namespace or configured).strip()
        if service == "kubernetes-cluster" or scope.lower() in {"", "all", "*", "-"}:
            scope = ""
        if template.id == "k8s_api_abnormal_pods":
            path = f"/api/v1/namespaces/{scope}/pods" if scope else "/api/v1/pods"
            payload = await self._request_json(datasource, "GET", path, params={"limit": 500})
            items = self._kubernetes_abnormal_pods(self._kubernetes_items(payload))
        elif template.id == "k8s_api_workload_status":
            objects: list[dict[str, Any]] = []
            for kind, plural in (
                ("Deployment", "deployments"),
                ("StatefulSet", "statefulsets"),
                ("DaemonSet", "daemonsets"),
            ):
                path = (
                    f"/apis/apps/v1/namespaces/{scope}/{plural}"
                    if scope
                    else f"/apis/apps/v1/{plural}"
                )
                payload = await self._request_json(
                    datasource,
                    "GET",
                    path,
                    params={"limit": 500},
                )
                for item in self._kubernetes_items(payload):
                    item.setdefault("kind", kind)
                    objects.append(item)
            items = self._kubernetes_unhealthy_workloads(objects)
        elif template.id == "k8s_api_node_conditions":
            payload = await self._request_json(
                datasource, "GET", "/api/v1/nodes", params={"limit": 500}
            )
            items = self._kubernetes_unhealthy_nodes(self._kubernetes_items(payload))
        elif template.id == "k8s_api_warning_events":
            path = f"/api/v1/namespaces/{scope}/events" if scope else "/api/v1/events"
            payload = await self._request_json(
                datasource,
                "GET",
                path,
                params={"limit": 500, "fieldSelector": "type=Warning"},
            )
            items = self._kubernetes_warning_events(self._kubernetes_items(payload), start, end)
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

    async def _request_json(
        self,
        datasource: DatasourceConfig,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        secrets = self.vault.decrypt(datasource.secret_ref)
        headers, auth = self._request_auth(datasource, secrets)
        tenant_id = str(datasource.settings.get("tenant_id", "")).strip()
        if tenant_id:
            headers["X-Scope-OrgID"] = tenant_id
        async with httpx.AsyncClient(
            base_url=datasource.base_url.rstrip("/"),
            timeout=self.settings.datasource_timeout_seconds,
            headers=headers,
            auth=auth,
            verify=self._request_verify(datasource, secrets),
            trust_env=False,
        ) as client:
            response = await client.request(method, path, params=params, json=json)
            response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError:
                return {"text": response.text[:4000]}

    @staticmethod
    def _request_auth(
        datasource: DatasourceConfig,
        secrets: dict[str, str],
    ) -> tuple[dict[str, str], httpx.Auth | None]:
        auth_type = str(datasource.settings.get("auth_type", "none")).strip().lower()
        headers: dict[str, str] = {}
        if auth_type == "none":
            return headers, None
        if auth_type == "bearer":
            token = secrets.get("token", "").strip()
            if not token:
                raise RuntimeError("数据源缺少 Bearer Token")
            headers["Authorization"] = f"Bearer {token}"
            return headers, None
        if auth_type == "basic":
            username = secrets.get("username", "").strip()
            password = secrets.get("password", "")
            if not username or not password:
                raise RuntimeError("数据源缺少 Basic Auth 用户名或密码")
            return headers, httpx.BasicAuth(username, password)
        if auth_type == "api_key":
            api_key = secrets.get("api_key", "").strip()
            if not api_key:
                raise RuntimeError("数据源缺少 API Key")
            header = str(datasource.settings.get("api_key_header", "Authorization")).strip()
            header = header or "Authorization"
            headers[header] = f"ApiKey {api_key}" if header.lower() == "authorization" else api_key
            return headers, None
        raise RuntimeError(f"不支持的数据源认证类型: {auth_type}")

    @staticmethod
    def _request_verify(
        datasource: DatasourceConfig,
        secrets: dict[str, str],
    ) -> bool | ssl.SSLContext:
        verify_ssl = bool(datasource.settings.get("verify_ssl", True))
        ca_cert = secrets.get("ca_cert")
        client_cert = secrets.get("client_cert")
        client_key = secrets.get("client_key")
        if not client_cert and not client_key:
            if not verify_ssl:
                return False
            return ssl.create_default_context(cadata=ca_cert) if ca_cert else True
        if not client_cert or not client_key:
            raise RuntimeError("客户端证书和私钥必须同时配置")
        context = (
            ssl.create_default_context(cadata=ca_cert)
            if verify_ssl
            else ssl._create_unverified_context()  # noqa: SLF001
        )
        with (
            tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as cert_file,
            tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as key_file,
        ):
            cert_file.write(client_cert)
            cert_file.flush()
            key_file.write(client_key)
            key_file.flush()
            context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
        return context

    @classmethod
    def _prometheus_series(cls, payload: object) -> tuple[str | None, list[dict[str, Any]]]:
        root = cls._unwrap_payload(payload)
        if isinstance(root, dict) and "data" in root:
            root = root["data"]
        result_type = root.get("resultType") if isinstance(root, dict) else None
        raw = root.get("result", []) if isinstance(root, dict) else root
        if not isinstance(raw, list):
            return result_type, []
        series: list[dict[str, Any]] = []
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            values = item.get("values")
            if not isinstance(values, list) and isinstance(item.get("value"), list):
                values = [item["value"]]
            series.append(
                {
                    "metric": item.get("metric", {}),
                    "values": values[-120:] if isinstance(values, list) else [],
                }
            )
        return str(result_type) if result_type else None, series

    @classmethod
    def _loki_entries(cls, payload: object, limit: int) -> list[dict[str, Any]]:
        root = cls._unwrap_payload(payload)
        data = root.get("data", root) if isinstance(root, dict) else root
        if isinstance(data, dict) and isinstance(data.get("result"), list):
            entries = [
                {
                    "timestamp_ns": str(value[0]),
                    "timestamp": cls._loki_timestamp(value[0]),
                    "labels": stream.get("stream", {}),
                    "line": redact(str(value[1]))[:1000],
                }
                for stream in data["result"]
                if isinstance(stream, dict)
                for value in stream.get("values", [])
                if isinstance(value, list) and len(value) == 2
            ]
        elif isinstance(data, list):
            entries = [
                {
                    "timestamp_ns": str(item.get("timestamp", "")),
                    "timestamp": item.get("timestamp"),
                    "labels": item.get("labels", {}),
                    "line": redact(str(item.get("line", item.get("message", ""))))[:1000],
                }
                for item in data
                if isinstance(item, dict)
            ]
        else:
            entries = []
        entries.sort(key=lambda item: item["timestamp_ns"], reverse=True)
        for entry in entries:
            entry.pop("timestamp_ns", None)
        return entries[:limit]

    @staticmethod
    def _loki_timestamp(value: object) -> str | None:
        try:
            return datetime.fromtimestamp(int(str(value)) / 1_000_000_000, UTC).isoformat()
        except (TypeError, ValueError, OverflowError):
            return str(value)[:100] or None

    @classmethod
    def _elasticsearch_entries(cls, payload: object, limit: int) -> list[dict[str, Any]]:
        root = cls._unwrap_payload(payload)
        if isinstance(root, dict) and isinstance(root.get("hits"), dict):
            raw = root["hits"].get("hits", [])
        elif isinstance(root, dict) and isinstance(root.get("data"), list):
            raw = root["data"]
        elif isinstance(root, list):
            raw = root
        else:
            text = cls._payload_text(root)
            return [{"message": redact(text)[:1000]}] if text else []
        entries: list[dict[str, Any]] = []
        for hit in raw[:limit] if isinstance(raw, list) else []:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source", hit)
            if not isinstance(source, dict):
                continue
            service = source.get("service.name")
            if service is None and isinstance(source.get("service"), dict):
                service = source["service"].get("name")
            level = source.get("log.level")
            if level is None and isinstance(source.get("log"), dict):
                level = source["log"].get("level")
            entries.append(
                {
                    "timestamp": source.get("@timestamp", source.get("timestamp")),
                    "service": service,
                    "level": level,
                    "message": redact(str(source.get("message", "")))[:1000],
                }
            )
        return entries

    @staticmethod
    def _elastic_query(query: str, service: str | None) -> str:
        if not service:
            return query
        safe_service = service.replace('"', "")
        return f'service.name:"{safe_service}" AND ({query})'

    @classmethod
    def _unwrap_payload(cls, payload: object) -> object:
        current = payload
        for _ in range(3):
            if not isinstance(current, dict):
                break
            for key in ("result", "output"):
                if key in current and len(current) == 1:
                    current = current[key]
                    break
            else:
                break
        return current

    @classmethod
    def _kubernetes_items(cls, payload: object) -> list[dict[str, Any]]:
        root = cls._unwrap_payload(payload)
        if isinstance(root, dict) and isinstance(root.get("items"), list):
            raw = root["items"]
        elif isinstance(root, list):
            raw = root
        elif isinstance(root, dict) and root.get("kind"):
            raw = [root]
        else:
            return []
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _kubernetes_abnormal_pods(pods: list[dict[str, Any]]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for pod in pods:
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
            if phase == "Succeeded" or (phase == "Running" and ready and not waiting_reasons):
                continue
            owners = metadata.get("ownerReferences", []) or []
            owner = owners[0] if owners else {}
            reason = ", ".join(dict.fromkeys(waiting_reasons)) or status.get("reason") or phase
            name = str(metadata.get("name", "unknown"))
            namespace = str(metadata.get("namespace", "default"))
            findings.append(
                {
                    "kind": "Pod",
                    "namespace": namespace,
                    "name": name,
                    "phase": phase,
                    "reason": reason,
                    "message": redact(str(status.get("message") or ""))[:500],
                    "owner": f"{owner.get('kind')}/{owner.get('name')}" if owner else None,
                    "containers": containers,
                    "summary": f"{namespace}/{name}: phase={phase}, reason={reason}",
                }
            )
        return findings

    @classmethod
    def _kubernetes_unhealthy_workloads(
        cls, workloads: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for workload in workloads:
            kind = str(workload.get("kind", "Workload"))
            metadata = workload.get("metadata", {})
            spec = workload.get("spec", {})
            status = workload.get("status", {})
            desired, ready = cls._workload_replicas(kind, spec, status)
            if ready >= desired:
                continue
            name = str(metadata.get("name", "unknown"))
            namespace = str(metadata.get("namespace", "default"))
            findings.append(
                {
                    "kind": kind,
                    "namespace": namespace,
                    "name": name,
                    "desired": desired,
                    "ready": ready,
                    "unavailable": max(0, desired - ready),
                    "summary": f"{namespace}/{kind}/{name}: ready={ready}/{desired}",
                }
            )
        return findings

    @staticmethod
    def _kubernetes_unhealthy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for node in nodes:
            conditions = node.get("status", {}).get("conditions", []) or []
            problems = [
                {
                    "type": item.get("type"),
                    "status": item.get("status"),
                    "reason": item.get("reason"),
                    "message": redact(str(item.get("message") or ""))[:500],
                }
                for item in conditions
                if (item.get("type") == "Ready" and item.get("status") != "True")
                or (
                    item.get("type")
                    in {"MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable"}
                    and item.get("status") == "True"
                )
            ]
            if problems:
                name = str(node.get("metadata", {}).get("name", "unknown"))
                findings.append(
                    {
                        "kind": "Node",
                        "name": name,
                        "conditions": problems,
                        "summary": f"Node/{name}: "
                        + ", ".join(f"{item['type']}={item['status']}" for item in problems),
                    }
                )
        return findings

    @classmethod
    def _kubernetes_warning_events(
        cls,
        events: list[dict[str, Any]],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for event in events:
            if event.get("type") not in {None, "Warning"}:
                continue
            metadata = event.get("metadata", {})
            involved = event.get("involvedObject", event.get("regarding", {}))
            event_time = cls._parse_kubernetes_time(
                event.get("eventTime")
                or event.get("lastTimestamp")
                or metadata.get("creationTimestamp")
            )
            if event_time and not (start.astimezone(UTC) <= event_time <= end.astimezone(UTC)):
                continue
            name = str(involved.get("name", "unknown"))
            namespace = str(involved.get("namespace") or metadata.get("namespace") or "-")
            reason = str(event.get("reason", "Warning"))
            message = redact(str(event.get("message") or event.get("note") or ""))[:800]
            findings.append(
                {
                    "kind": "Event",
                    "namespace": namespace,
                    "name": name,
                    "object_kind": involved.get("kind"),
                    "reason": reason,
                    "message": message,
                    "count": int(event.get("count", 1) or 1),
                    "observed_at": event_time.isoformat() if event_time else None,
                    "summary": f"{namespace}/{involved.get('kind', 'Object')}/{name}: "
                    f"{reason} - {message}",
                }
            )
        findings.sort(key=lambda item: str(item.get("observed_at") or ""), reverse=True)
        return findings[:30]

    @staticmethod
    def _workload_replicas(
        kind: str, spec: dict[str, Any], status: dict[str, Any]
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
    def _tempo_trace_summary(item: object) -> dict[str, Any]:
        trace = item if isinstance(item, dict) else {}
        start_ns = str(trace.get("startTimeUnixNano", ""))
        start_time: Any
        try:
            start_time = datetime.fromtimestamp(int(start_ns) / 1_000_000_000, UTC).isoformat()
        except (TypeError, ValueError, OverflowError):
            start_time = trace.get("start_time") or trace.get("startTime")
        span_sets = trace.get("spanSets", [])
        if not isinstance(span_sets, list):
            span_sets = []
        matched = sum(
            DatasourceGateway._tempo_int(item.get("matched", 0))
            for item in span_sets
            if isinstance(item, dict)
        )
        return {
            "trace_id": str(trace.get("traceID", trace.get("trace_id", "")))[:64],
            "root_service_name": redact(
                str(trace.get("rootServiceName", trace.get("root_service_name", "")))
            )[:300],
            "root_trace_name": redact(
                str(trace.get("rootTraceName", trace.get("root_trace_name", "")))
            )[:500],
            "start_time": start_time,
            "duration_ms": trace.get("durationMs", trace.get("duration_ms")),
            "matched_spans": matched or trace.get("matched_spans", 0),
        }

    def _tempo_spans(self, payload: object, *, limit: int) -> tuple[list[dict[str, Any]], int]:
        root = self._unwrap_payload(payload)
        if not isinstance(root, dict):
            return [], 0
        trace = root.get("trace", root)
        if not isinstance(trace, dict):
            return [], 0
        resource_spans = trace.get("resourceSpans") or trace.get("batches") or []
        if not isinstance(resource_spans, list):
            return [], 0
        spans: list[dict[str, Any]] = []
        total = 0
        for resource_span in resource_spans:
            if not isinstance(resource_span, dict):
                continue
            resource = resource_span.get("resource", {})
            attributes = self._tempo_attributes(
                resource.get("attributes", []) if isinstance(resource, dict) else []
            )
            service_name = str(attributes.get("service.name", ""))[:300]
            scopes = resource_span.get("scopeSpans") or resource_span.get(
                "instrumentationLibrarySpans", []
            )
            for scope in scopes if isinstance(scopes, list) else []:
                raw_spans = scope.get("spans", []) if isinstance(scope, dict) else []
                if not isinstance(raw_spans, list):
                    continue
                total += len(raw_spans)
                for span in raw_spans:
                    if len(spans) < limit and isinstance(span, dict):
                        spans.append(self._tempo_span(span, service_name))
        return spans, total

    def _tempo_span(self, span: dict[str, Any], service_name: str) -> dict[str, Any]:
        start_ns = self._tempo_int(span.get("startTimeUnixNano"))
        end_ns = self._tempo_int(span.get("endTimeUnixNano"))
        status = span.get("status", {})
        if not isinstance(status, dict):
            status = {}
        return {
            "span_id": str(span.get("spanId", ""))[:32],
            "parent_span_id": str(span.get("parentSpanId") or "")[:32] or None,
            "service_name": redact(service_name),
            "name": redact(str(span.get("name", "")))[:500],
            "start_time": datetime.fromtimestamp(start_ns / 1_000_000_000, UTC).isoformat()
            if start_ns
            else None,
            "duration_ms": round((end_ns - start_ns) / 1_000_000, 3)
            if end_ns >= start_ns and start_ns
            else None,
            "status": status.get("code"),
            "status_message": redact(str(status.get("message", "")))[:500],
            "attributes": self._tempo_attributes(span.get("attributes", [])),
        }

    @classmethod
    def _tempo_attributes(cls, attributes: object) -> dict[str, Any]:
        if not isinstance(attributes, list):
            return {}
        result: dict[str, Any] = {}
        for attribute in attributes[:30]:
            if not isinstance(attribute, dict):
                continue
            key = str(attribute.get("key", ""))[:200]
            value = attribute.get("value")
            if not key or not isinstance(value, dict):
                continue
            decoded = next(
                (
                    value[name]
                    for name in (
                        "stringValue",
                        "boolValue",
                        "intValue",
                        "doubleValue",
                        "bytesValue",
                    )
                    if name in value
                ),
                str(value)[:1000],
            )
            result[key] = (
                "[REDACTED]"
                if re.search(r"(?i)(authorization|token|password|secret|api[._-]?key)", key)
                else redact(str(decoded))[:1000]
                if isinstance(decoded, str)
                else decoded
            )
        return result

    @staticmethod
    def _tempo_int(value: object) -> int:
        try:
            return int(value) if isinstance(value, (str, bytes, int, float)) else 0
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _payload_text(cls, payload: object) -> str:
        root = cls._unwrap_payload(payload)
        text = root.get("text") if isinstance(root, dict) else None
        if isinstance(text, str):
            return text
        return ""

    @staticmethod
    def _is_number(value: object) -> bool:
        try:
            float(value)  # type: ignore[arg-type]
            return True
        except (TypeError, ValueError):
            return False

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
        if template.kind == "trace":
            return ToolResult(
                source=template.source,
                query_pack=template.query_pack,
                template_id=template.id,
                status="completed",
                result_count=1,
                data={
                    "traces": [
                        {
                            "trace_id": "0123456789abcdef0123456789abcdef",
                            "root_service_name": service,
                            "root_trace_name": "POST /checkout",
                            "start_time": observed_at.isoformat(),
                            "duration_ms": 3200,
                            "matched_spans": 2,
                        }
                    ],
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
