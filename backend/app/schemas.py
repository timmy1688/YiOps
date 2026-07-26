from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DatasourceCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["prometheus", "loki", "elasticsearch", "kubernetes"]
    base_url: HttpUrl
    secret_ref: str | None = None
    credential: str | None = None
    ca_cert: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DatasourceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    secret_ref: str | None = None
    credential: str | None = None
    ca_cert: str | None = None
    settings: dict[str, Any] | None = None
    enabled: bool | None = None


class DatasourceRead(APIModel):
    id: str
    name: str
    type: str
    base_url: str
    secret_configured: bool
    settings: dict[str, Any]
    enabled: bool
    last_test_status: str | None
    last_tested_at: datetime | None


class AlertIntegrationCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["alertmanager"] = "alertmanager"
    default_cluster: str = Field(min_length=1, max_length=255)
    default_namespace: str | None = Field(default=None, max_length=255)
    auto_analyze: bool = False
    enabled: bool = True


class AlertIntegrationUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_cluster: str | None = Field(default=None, max_length=255)
    default_namespace: str | None = Field(default=None, max_length=255)
    auto_analyze: bool | None = None
    enabled: bool | None = None


class AlertIntegrationRead(APIModel):
    id: str
    name: str
    type: str
    webhook_path: str
    default_cluster: str | None
    default_namespace: str | None
    auto_analyze: bool
    enabled: bool
    received_count: int
    last_received_at: datetime | None
    created_at: datetime


class AnalysisModelConfigUpsert(APIModel):
    name: str = Field(default="DeepSeek", min_length=1, max_length=120)
    provider: Literal["deepseek", "openai_compatible"] = "deepseek"
    base_url: HttpUrl
    model_name: str = Field(min_length=1, max_length=120)
    api_key: str | None = Field(default=None, min_length=1)
    enabled: bool = True


class AnalysisModelConfigRead(APIModel):
    id: str
    name: str
    provider: str
    base_url: str
    model_name: str
    api_key_configured: bool
    enabled: bool
    last_test_status: str | None
    last_test_message: str | None
    last_tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ManualIncidentCreate(APIModel):
    alert_name: str
    service: str
    cluster: str | None = None
    namespace: str | None = None
    instance: str | None = None
    severity: Literal["info", "warning", "critical"] = "warning"
    started_at: datetime
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)


class IncidentRead(APIModel):
    id: str
    title: str
    service: str
    cluster: str | None
    namespace: str | None
    severity: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    alert_count: int
    is_test: bool = False
    source: str | None = None
    created_at: datetime
    latest_run: "AnalysisRunRead | None" = None


class AnalysisRunRead(APIModel):
    id: str
    incident_id: str
    status: str
    current_step: str | None
    progress: float
    model_name: str
    error_code: str | None
    error_message: str | None
    input_tokens: int
    output_tokens: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class EvidenceRead(APIModel):
    id: str
    analysis_run_id: str
    tool_execution_id: str | None
    type: str
    source: str
    title: str
    summary: str
    observed_at: datetime | None
    subject: dict[str, Any]
    values: dict[str, Any]
    quality: float


class ToolExecutionRead(APIModel):
    id: str
    source: str
    query_pack: str
    template_id: str
    parameters: dict[str, Any]
    status: str
    duration_ms: int
    result_count: int
    result_summary: dict[str, Any] | None
    error_code: str | None
    created_at: datetime


class Hypothesis(APIModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class RootCauseOutput(APIModel):
    summary: str
    confidence: float = Field(ge=0, le=1)
    hypotheses: list[Hypothesis]
    recommended_actions: list[str]
    missing_evidence: list[str]


class RootCauseReportRead(RootCauseOutput):
    id: str
    analysis_run_id: str
    status: str
    created_at: datetime


class FeedbackCreate(APIModel):
    verdict: Literal["correct", "partially_correct", "incorrect", "unknown"]
    actual_root_cause: str | None = None
    comment: str | None = None


class FeedbackRead(FeedbackCreate):
    id: str
    report_id: str
    created_at: datetime


class QueryPackPlan(APIModel):
    query_packs: list[
        Literal[
            "service_health",
            "runtime_resource",
            "instance_health",
            "dependency_health",
            "database_symptom",
            "application_errors",
            "kubernetes_cluster",
        ]
    ] = Field(min_length=1, max_length=7)
