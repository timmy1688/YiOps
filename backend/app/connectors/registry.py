from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    type: str
    display_name: str
    health_path: str
    capabilities: tuple[str, ...]
    credential_kind: str = "none"

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


class ConnectorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ConnectorSpec] = {}

    def register(self, spec: ConnectorSpec) -> None:
        if spec.type in self._items:
            raise ValueError(f"Connector already registered: {spec.type}")
        self._items[spec.type] = spec

    def get(self, connector_type: str) -> ConnectorSpec:
        try:
            return self._items[connector_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported connector type: {connector_type}") from exc

    def all(self) -> tuple[ConnectorSpec, ...]:
        return tuple(self._items.values())


registry = ConnectorRegistry()
registry.register(
    ConnectorSpec(
        type="prometheus",
        display_name="Prometheus",
        health_path="/-/healthy",
        capabilities=("metrics", "range_query", "query_pack"),
    )
)
registry.register(
    ConnectorSpec(
        type="loki",
        display_name="Loki",
        health_path="/ready",
        capabilities=("logs", "range_query", "query_pack"),
    )
)
registry.register(
    ConnectorSpec(
        type="elasticsearch",
        display_name="Elasticsearch",
        health_path="/",
        capabilities=("logs", "search", "query_pack"),
    )
)
registry.register(
    ConnectorSpec(
        type="kubernetes",
        display_name="Kubernetes",
        health_path="/version",
        capabilities=("objects", "events", "workloads", "query_pack"),
        credential_kind="service_account",
    )
)
