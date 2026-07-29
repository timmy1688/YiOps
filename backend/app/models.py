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


class DatasourceConfig(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
    name = fields.CharField(max_length=120, unique=True)
    type = fields.CharField(max_length=32, db_index=True)
    base_url = fields.CharField(max_length=500)
    secret_ref = fields.TextField(null=True)
    settings = fields.JSONField(default=dict)
    enabled = fields.BooleanField(default=True)
    last_test_status = fields.CharField(max_length=32, null=True)
    last_tested_at = fields.DatetimeField(null=True)

    class Meta:
        table = "datasource_configs"


class AlertIntegration(TimestampModel):
    id = fields.CharField(max_length=48, primary_key=True)
    name = fields.CharField(max_length=120, unique=True)
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


class AnalysisModelConfig(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
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


class Incident(TimestampModel):
    id = fields.CharField(max_length=40, primary_key=True)
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
        indexes = (("status", "started_at"), ("service", "started_at"))


class AlertEvent(Model):
    id = fields.CharField(max_length=40, primary_key=True)
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
        unique_together = (("fingerprint", "started_at"),)
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
