from uuid import uuid4

from tortoise import fields
from tortoise.models import Model


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class TimestampModel(Model):
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True


class Tenant(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    name = fields.CharField(max_length=120)
    slug = fields.CharField(max_length=80, unique=True)
    active = fields.BooleanField(default=True)

    class Meta:
        table = "tenants"


class User(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="users")
    username = fields.CharField(max_length=120, unique=True)
    display_name = fields.CharField(max_length=120)
    password_hash = fields.CharField(max_length=500)
    role = fields.CharField(max_length=32, default="admin")
    active = fields.BooleanField(default=True)
    last_login_at = fields.DatetimeField(null=True)

    class Meta:
        table = "users"
        indexes = (("tenant_id", "active"),)


class UserSession(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    user = fields.ForeignKeyField("models.User", related_name="sessions")
    token_hash = fields.CharField(max_length=64, unique=True)
    csrf_token_hash = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField(db_index=True)
    last_seen_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user_sessions"
        indexes = (("user_id", "expires_at"),)


class DatasourceConfig(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="datasources")
    name = fields.CharField(max_length=120)
    type = fields.CharField(max_length=32, db_index=True)
    base_url = fields.CharField(max_length=500)
    secret_ref = fields.TextField(null=True)
    settings = fields.JSONField(default=dict)
    enabled = fields.BooleanField(default=True)
    last_test_status = fields.CharField(max_length=32, null=True)
    last_tested_at = fields.DatetimeField(null=True)

    class Meta:
        table = "datasource_configs"
        unique_together = (("tenant_id", "name"),)


class AlertIntegration(TimestampModel):
    id = fields.CharField(max_length=48, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="alert_integrations")
    name = fields.CharField(max_length=120)
    type = fields.CharField(max_length=32, default="alertmanager")
    webhook_token = fields.CharField(max_length=64, unique=True)
    default_cluster = fields.CharField(max_length=255, null=True)
    default_namespace = fields.CharField(max_length=255, null=True)
    auto_analyze = fields.BooleanField(default=True)
    enabled = fields.BooleanField(default=True)
    received_count = fields.IntField(default=0)
    last_received_at = fields.DatetimeField(null=True)

    class Meta:
        table = "alert_integrations"
        unique_together = (("tenant_id", "name"),)


class AnalysisModelConfig(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="model_configs")
    name = fields.CharField(max_length=120, default="DeepSeek")
    provider = fields.CharField(max_length=32, default="deepseek")
    base_url = fields.CharField(max_length=500)
    model_name = fields.CharField(max_length=120)
    secret_ref = fields.TextField(null=True)
    enabled = fields.BooleanField(default=True)
    last_test_status = fields.CharField(max_length=32, null=True)
    last_test_message = fields.TextField(null=True)
    last_tested_at = fields.DatetimeField(null=True)

    class Meta:
        table = "analysis_model_configs"
        unique_together = (("tenant_id", "name"),)


class Incident(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="incidents")
    aggregation_key = fields.CharField(max_length=500, db_index=True)
    title = fields.CharField(max_length=500)
    service = fields.CharField(max_length=255, db_index=True)
    cluster = fields.CharField(max_length=255, null=True)
    namespace = fields.CharField(max_length=255, null=True)
    severity = fields.CharField(max_length=32, default="warning")
    status = fields.CharField(max_length=32, default="open", db_index=True)
    started_at = fields.DatetimeField(db_index=True)
    ended_at = fields.DatetimeField(null=True)
    alert_count = fields.IntField(default=1)

    class Meta:
        table = "incidents"
        indexes = (("tenant_id", "status", "started_at"), ("tenant_id", "service"))


class AlertEvent(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="alert_events")
    source = fields.CharField(max_length=32, default="alertmanager")
    external_id = fields.CharField(max_length=255, null=True)
    fingerprint = fields.CharField(max_length=64)
    alert_name = fields.CharField(max_length=255)
    service = fields.CharField(max_length=255)
    cluster = fields.CharField(max_length=255, null=True)
    namespace = fields.CharField(max_length=255, null=True)
    instance = fields.CharField(max_length=255, null=True)
    severity = fields.CharField(max_length=32, default="warning")
    status = fields.CharField(max_length=32, default="firing")
    started_at = fields.DatetimeField()
    ended_at = fields.DatetimeField(null=True)
    labels = fields.JSONField(default=dict)
    annotations = fields.JSONField(default=dict)
    incident = fields.ForeignKeyField("models.Incident", related_name="alerts")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "alert_events"
        unique_together = (("tenant_id", "fingerprint", "started_at"),)
        indexes = (("incident_id", "created_at"),)


class AnalysisRun(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    incident = fields.ForeignKeyField("models.Incident", related_name="analysis_runs")
    status = fields.CharField(max_length=32, default="queued", db_index=True)
    current_step = fields.CharField(max_length=64, null=True)
    progress = fields.FloatField(default=0.0)
    model_name = fields.CharField(max_length=120)
    investigation_plan = fields.JSONField(null=True)
    error_code = fields.CharField(max_length=120, null=True)
    error_message = fields.TextField(null=True)
    input_tokens = fields.IntField(default=0)
    output_tokens = fields.IntField(default=0)
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "analysis_runs"
        indexes = (("incident_id", "created_at"),)


class ToolExecution(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    analysis_run = fields.ForeignKeyField("models.AnalysisRun", related_name="tool_executions")
    source = fields.CharField(max_length=32)
    query_pack = fields.CharField(max_length=64)
    template_id = fields.CharField(max_length=120)
    parameters = fields.JSONField(default=dict)
    status = fields.CharField(max_length=32)
    duration_ms = fields.IntField(default=0)
    result_count = fields.IntField(default=0)
    result_summary = fields.JSONField(null=True)
    error_code = fields.CharField(max_length=120, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "tool_executions"
        unique_together = (("analysis_run_id", "template_id"),)


class EvidenceItem(Model):
    id = fields.CharField(max_length=48, primary_key=True)
    analysis_run = fields.ForeignKeyField("models.AnalysisRun", related_name="evidence_items")
    tool_execution = fields.ForeignKeyField(
        "models.ToolExecution",
        related_name="evidence_items",
        null=True,
    )
    type = fields.CharField(max_length=64)
    source = fields.CharField(max_length=32)
    title = fields.CharField(max_length=500)
    summary = fields.TextField()
    observed_at = fields.DatetimeField(null=True)
    subject = fields.JSONField(default=dict)
    values = fields.JSONField(default=dict)
    quality = fields.FloatField(default=0.8)
    content_hash = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "evidence_items"
        unique_together = (("analysis_run_id", "content_hash"),)
        indexes = (("analysis_run_id", "type"),)


class RootCauseReport(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    analysis_run = fields.OneToOneField("models.AnalysisRun", related_name="report")
    status = fields.CharField(max_length=32)
    summary = fields.TextField()
    confidence = fields.FloatField()
    hypotheses = fields.JSONField(default=list)
    recommended_actions = fields.JSONField(default=list)
    missing_evidence = fields.JSONField(default=list)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "root_cause_reports"


class UserFeedback(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    report = fields.ForeignKeyField("models.RootCauseReport", related_name="feedback")
    verdict = fields.CharField(max_length=32)
    actual_root_cause = fields.TextField(null=True)
    comment = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user_feedback"


class Investigation(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="investigations")
    incident = fields.ForeignKeyField("models.Incident", related_name="investigations", null=True)
    title = fields.CharField(max_length=500)
    status = fields.CharField(max_length=32, default="idle", db_index=True)
    current_step = fields.CharField(max_length=120, null=True)
    progress = fields.FloatField(default=0.0)
    model_name = fields.CharField(max_length=120, null=True)
    summary = fields.TextField(null=True)
    input_tokens = fields.IntField(default=0)
    output_tokens = fields.IntField(default=0)
    tool_count = fields.IntField(default=0)
    error_code = fields.CharField(max_length=120, null=True)
    error_message = fields.TextField(null=True)
    share_token = fields.CharField(max_length=64, unique=True, null=True)
    started_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "investigations"
        indexes = (("tenant_id", "status", "created_at"), ("incident_id", "created_at"))


class InvestigationMessage(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    investigation = fields.ForeignKeyField("models.Investigation", related_name="messages")
    role = fields.CharField(max_length=24)
    content = fields.TextField()
    model_name = fields.CharField(max_length=120, null=True)
    tool_calls = fields.JSONField(default=list)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "investigation_messages"
        indexes = (("investigation_id", "created_at"),)


class InvestigationStep(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    investigation = fields.ForeignKeyField("models.Investigation", related_name="steps")
    sequence = fields.IntField()
    name = fields.CharField(max_length=120)
    source = fields.CharField(max_length=40)
    status = fields.CharField(max_length=32, default="running")
    description = fields.TextField(null=True)
    parameters = fields.JSONField(default=dict)
    result_count = fields.IntField(default=0)
    duration_ms = fields.IntField(default=0)
    error_code = fields.CharField(max_length=120, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    completed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "investigation_steps"
        unique_together = (("investigation_id", "sequence"),)


class InvestigationEvidence(Model):
    id = fields.CharField(max_length=48, primary_key=True)
    investigation = fields.ForeignKeyField("models.Investigation", related_name="evidence")
    step = fields.ForeignKeyField("models.InvestigationStep", related_name="evidence", null=True)
    source = fields.CharField(max_length=40)
    title = fields.CharField(max_length=500)
    summary = fields.TextField()
    observed_at = fields.DatetimeField(null=True)
    subject = fields.JSONField(default=dict)
    values = fields.JSONField(default=dict)
    quality = fields.FloatField(default=0.8)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "investigation_evidence"
        indexes = (("investigation_id", "created_at"),)


class InvestigationHypothesis(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    investigation = fields.ForeignKeyField("models.Investigation", related_name="hypotheses")
    cause = fields.TextField()
    confidence = fields.FloatField(default=0.0)
    status = fields.CharField(max_length=32, default="candidate")
    supporting_evidence_ids = fields.JSONField(default=list)
    contradicting_evidence_ids = fields.JSONField(default=list)
    missing_evidence = fields.JSONField(default=list)

    class Meta:
        table = "investigation_hypotheses"
        indexes = (("investigation_id", "confidence"),)


class InvestigationEvent(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    investigation = fields.ForeignKeyField("models.Investigation", related_name="events")
    event_type = fields.CharField(max_length=64)
    payload = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "investigation_events"
        indexes = (("investigation_id", "created_at"),)


class EvaluationRun(Model):
    id = fields.CharField(max_length=40, primary_key=True)
    tenant = fields.ForeignKeyField("models.Tenant", related_name="evaluation_runs")
    benchmark = fields.CharField(max_length=120)
    engine = fields.CharField(max_length=120, default="evidence-rules-baseline")
    scenario_count = fields.IntField()
    aggregate = fields.JSONField(default=dict)
    categories = fields.JSONField(default=dict)
    results = fields.JSONField(default=list)
    duration_ms = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "evaluation_runs"
        indexes = (("tenant_id", "created_at"),)
