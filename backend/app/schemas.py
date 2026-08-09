from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthStatusRead(APIModel):
    enabled: bool
    authenticated: bool


class LoginRequest(APIModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


class PasswordChangeRequest(APIModel):
    current_password: str = Field(min_length=1, max_length=500)
    new_password: str = Field(min_length=12, max_length=500)


class CurrentUserRead(APIModel):
    id: str
    username: str
    display_name: str
    role: str
    tenant_id: str
    tenant_name: str


class EvaluationRunRead(APIModel):
    id: str
    benchmark: str
    engine: str
    scenario_count: int
    aggregate: dict[str, float]
    categories: dict[str, dict[str, float]]
    results: list[dict[str, Any]]
    duration_ms: int
    created_at: datetime


class DatasourceCreate(APIModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["prometheus", "loki", "tempo", "elasticsearch", "kubernetes"]
    base_url: HttpUrl | None = None
    auth_type: Literal["none", "bearer", "basic", "api_key"] = "none"
    username: str | None = Field(default=None, max_length=255)
    credential: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DatasourceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    auth_type: Literal["none", "bearer", "basic", "api_key"] | None = None
    username: str | None = Field(default=None, max_length=255)
    credential: str | None = None
    settings: dict[str, Any] | None = None
    enabled: bool | None = None


class DatasourceRead(APIModel):
    id: str
    name: str
    type: str
    base_url: str
    auth_type: str
    username: str | None
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
    auto_analyze: bool = True
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
    name: str = Field(min_length=1, max_length=120)
    # "deepseek" is accepted for compatibility with clients from the
    # single-channel version. Both values use the same OpenAI protocol.
    provider: Literal["openai_compatible", "deepseek"] = "openai_compatible"
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


class ChatMessage(APIModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(APIModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=24)
    incident_id: str | None = Field(default=None, max_length=40)


class ChatToolCallRead(APIModel):
    name: str
    status: str
    result_count: int
    duration_ms: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class ChatResponse(APIModel):
    content: str
    model_name: str
    context_scope: str
    tool_calls: list[ChatToolCallRead] = Field(default_factory=list)
    conversation_id: str | None = None
    conversation_title: str | None = None


class ChatConversationCreate(APIModel):
    title: str | None = Field(default=None, max_length=300)
    incident_id: str | None = Field(default=None, max_length=40)


class ChatConversationImport(ChatConversationCreate):
    messages: list[ChatMessage] = Field(min_length=1, max_length=24)


class ChatConversationUpdate(APIModel):
    title: str = Field(min_length=1, max_length=300)


class ChatConversationMessageCreate(APIModel):
    content: str = Field(min_length=1, max_length=8000)


class ChatConversationMessageRead(APIModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    model_name: str | None
    tool_calls: list[ChatToolCallRead] = Field(default_factory=list)
    created_at: datetime


class ChatConversationRead(APIModel):
    id: str
    title: str
    incident_id: str | None
    message_count: int
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChatConversationDetail(ChatConversationRead):
    messages: list[ChatConversationMessageRead] = Field(default_factory=list)


class InvestigationCreate(APIModel):
    title: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=8000)
    incident_id: str | None = Field(default=None, max_length=40)


class InvestigationMessageCreate(APIModel):
    content: str = Field(min_length=1, max_length=8000)


class InvestigationMessageRead(APIModel):
    id: str
    role: str
    content: str
    model_name: str | None
    tool_calls: list[dict[str, Any]]
    created_at: datetime


class InvestigationStepRead(APIModel):
    id: str
    sequence: int
    name: str
    source: str
    status: str
    description: str | None
    parameters: dict[str, Any]
    result_count: int
    duration_ms: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class InvestigationEvidenceRead(APIModel):
    id: str
    step_id: str | None
    source: str
    title: str
    summary: str
    observed_at: datetime | None
    subject: dict[str, Any]
    values: dict[str, Any]
    quality: float
    created_at: datetime


class InvestigationHypothesisRead(APIModel):
    id: str
    cause: str
    confidence: float
    status: str
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    missing_evidence: list[str]
    created_at: datetime
    updated_at: datetime


class InvestigationRead(APIModel):
    id: str
    incident_id: str | None
    title: str
    status: str
    current_step: str | None
    progress: float
    model_name: str | None
    summary: str | None
    input_tokens: int
    output_tokens: int
    tool_count: int
    error_code: str | None
    error_message: str | None
    share_token: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvestigationDetail(InvestigationRead):
    messages: list[InvestigationMessageRead] = Field(default_factory=list)
    steps: list[InvestigationStepRead] = Field(default_factory=list)
    evidence: list[InvestigationEvidenceRead] = Field(default_factory=list)
    hypotheses: list[InvestigationHypothesisRead] = Field(default_factory=list)


class InvestigationShareRead(APIModel):
    share_token: str
    share_path: str


class WikiDocumentCreate(APIModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=500_000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["draft", "published"] = "published"


class WikiDocumentUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1, max_length=500_000)
    tags: list[str] | None = Field(default=None, max_length=30)
    status: Literal["draft", "published"] | None = None


class WikiDocumentRead(APIModel):
    id: str
    title: str
    content: str
    tags: list[str]
    status: str
    version: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class WikiSearchRequest(APIModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=20)


class WikiSearchResult(APIModel):
    document_id: str
    title: str
    heading: str | None
    excerpt: str
    score: float
    version: int


QueryPackName = Literal[
    "service_health",
    "runtime_resource",
    "instance_health",
    "dependency_health",
    "database_symptom",
    "application_errors",
    "kubernetes_cluster",
]


class QueryPackPlan(APIModel):
    query_packs: list[QueryPackName] = Field(min_length=1, max_length=7)


class InvestigationRefinement(APIModel):
    query_packs: list[QueryPackName] = Field(default_factory=list, max_length=7)


class ReActDecision(APIModel):
    action: Literal["query", "finish"]
    query_pack: QueryPackName | None = None
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_action(self) -> "ReActDecision":
        if self.action == "query" and self.query_pack is None:
            raise ValueError("query action requires query_pack")
        if self.action == "finish":
            self.query_pack = None
        return self
