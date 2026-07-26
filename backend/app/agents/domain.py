from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SourceType = Literal["prometheus", "loki", "elasticsearch", "kubernetes"]


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    id: str
    query_pack: str
    source: SourceType
    query: str
    kind: Literal["metric", "log", "object"]
    title: str


@dataclass(slots=True)
class ToolResult:
    source: SourceType
    query_pack: str
    template_id: str
    status: str
    result_count: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error_code: str | None = None


@dataclass(slots=True)
class EvidenceRecord:
    id: str
    type: str
    source: str
    title: str
    summary: str
    observed_at: datetime | None
    subject: dict[str, Any]
    values: dict[str, Any]
    quality: float
    content_hash: str
    tool_execution_id: str | None = None
