from app.agents.domain import QueryTemplate

QUERY_TEMPLATES: tuple[QueryTemplate, ...] = (
    QueryTemplate(
        id="k8s_api_abnormal_pods",
        query_pack="kubernetes_cluster",
        source="kubernetes",
        query="pods",
        kind="object",
        title="Kubernetes API abnormal pods",
    ),
    QueryTemplate(
        id="k8s_api_workload_status",
        query_pack="kubernetes_cluster",
        source="kubernetes",
        query="workloads",
        kind="object",
        title="Kubernetes API unhealthy workloads",
    ),
    QueryTemplate(
        id="k8s_api_node_conditions",
        query_pack="kubernetes_cluster",
        source="kubernetes",
        query="nodes",
        kind="object",
        title="Kubernetes API unhealthy nodes",
    ),
    QueryTemplate(
        id="k8s_api_warning_events",
        query_pack="kubernetes_cluster",
        source="kubernetes",
        query="events",
        kind="object",
        title="Kubernetes API warning events",
    ),
    QueryTemplate(
        id="k8s_ready_nodes",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query='sum(kube_node_status_condition{condition="Ready",status="true"})',
        kind="metric",
        title="Kubernetes Ready nodes",
    ),
    QueryTemplate(
        id="k8s_not_ready_nodes",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query='sum(kube_node_status_condition{condition="Ready",status=~"false|unknown"})',
        kind="metric",
        title="Kubernetes NotReady nodes",
    ),
    QueryTemplate(
        id="k8s_running_pods",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query='sum(kube_pod_status_phase{phase="Running"})',
        kind="metric",
        title="Kubernetes running pods",
    ),
    QueryTemplate(
        id="k8s_abnormal_pods",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query='sum(kube_pod_status_phase{phase=~"Pending|Failed|Unknown"})',
        kind="metric",
        title="Kubernetes abnormal pods",
    ),
    QueryTemplate(
        id="k8s_unavailable_deployment_replicas",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query="sum(kube_deployment_status_replicas_unavailable)",
        kind="metric",
        title="Kubernetes unavailable deployment replicas",
    ),
    QueryTemplate(
        id="k8s_waiting_containers",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query="sum(kube_pod_container_status_waiting_reason)",
        kind="metric",
        title="Kubernetes waiting containers",
    ),
    QueryTemplate(
        id="k8s_container_restarts_1h",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query="sum(increase(kube_pod_container_status_restarts_total[1h]))",
        kind="metric",
        title="Kubernetes container restarts in 1h",
    ),
    QueryTemplate(
        id="k8s_cluster_cpu_utilization",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query='1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))',
        kind="metric",
        title="Kubernetes cluster CPU utilization",
    ),
    QueryTemplate(
        id="k8s_cluster_memory_utilization",
        query_pack="kubernetes_cluster",
        source="prometheus",
        query="1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)",
        kind="metric",
        title="Kubernetes cluster memory utilization",
    ),
    QueryTemplate(
        id="k8s_error_logs",
        query_pack="kubernetes_cluster",
        source="loki",
        query='{namespace=~"{namespace}"} |~ "(?i)(error|exception|failed|fatal)"',
        kind="log",
        title="Kubernetes error log patterns",
    ),
    QueryTemplate(
        id="http_request_rate",
        query_pack="service_health",
        source="prometheus",
        query='sum(rate(http_requests_total{service="{service}"}[5m]))',
        kind="metric",
        title="HTTP request rate",
    ),
    QueryTemplate(
        id="http_error_rate",
        query_pack="service_health",
        source="prometheus",
        query=(
            'sum(rate(http_requests_total{service="{service}",status=~"5.."}[5m]))'
            ' / clamp_min(sum(rate(http_requests_total{service="{service}"}[5m])), 1)'
        ),
        kind="metric",
        title="HTTP error rate",
    ),
    QueryTemplate(
        id="http_p99_latency",
        query_pack="service_health",
        source="prometheus",
        query=(
            "histogram_quantile(0.99, "
            'sum by (le) (rate(http_request_duration_seconds_bucket{service="{service}"}[5m])))'
        ),
        kind="metric",
        title="HTTP P99 latency",
    ),
    QueryTemplate(
        id="cpu_usage",
        query_pack="runtime_resource",
        source="prometheus",
        query='avg(rate(process_cpu_seconds_total{service="{service}"}[5m]))',
        kind="metric",
        title="CPU usage",
    ),
    QueryTemplate(
        id="memory_usage",
        query_pack="runtime_resource",
        source="prometheus",
        query='max(process_resident_memory_bytes{service="{service}"})',
        kind="metric",
        title="Memory usage",
    ),
    QueryTemplate(
        id="instance_up",
        query_pack="instance_health",
        source="prometheus",
        query='sum(up{service="{service}"})',
        kind="metric",
        title="Healthy instances",
    ),
    QueryTemplate(
        id="dependency_error_rate",
        query_pack="dependency_health",
        source="prometheus",
        query='sum(rate(outbound_requests_total{service="{service}",status="error"}[5m]))',
        kind="metric",
        title="Dependency error rate",
    ),
    QueryTemplate(
        id="dependency_latency",
        query_pack="dependency_health",
        source="prometheus",
        query='avg(rate(outbound_request_duration_seconds_sum{service="{service}"}[5m]))',
        kind="metric",
        title="Dependency latency",
    ),
    QueryTemplate(
        id="db_pool_active",
        query_pack="database_symptom",
        source="prometheus",
        query='max(db_pool_active_connections{service="{service}"})',
        kind="metric",
        title="Database pool active connections",
    ),
    QueryTemplate(
        id="db_pool_timeout_logs",
        query_pack="database_symptom",
        source="loki",
        query='{service="{service}"} |~ "(?i)(connection pool|timeout waiting for connection)"',
        kind="log",
        title="Database pool timeout logs",
    ),
    QueryTemplate(
        id="application_error_logs",
        query_pack="application_errors",
        source="loki",
        query=(
            '{service="{service}", namespace=~"{namespace}"} '
            '|~ "(?i)(error|exception|fatal)"'
        ),
        kind="log",
        title="Application error logs",
    ),
    QueryTemplate(
        id="application_error_events",
        query_pack="application_errors",
        source="elasticsearch",
        query="application_error_events",
        kind="log",
        title="Application error events",
    ),
)

TEMPLATES_BY_ID = {template.id: template for template in QUERY_TEMPLATES}


def templates_for_packs(query_packs: list[str]) -> list[QueryTemplate]:
    allowed = set(query_packs)
    return [template for template in QUERY_TEMPLATES if template.query_pack in allowed]
