from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `alert_integrations` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(48) NOT NULL PRIMARY KEY,
    `name` VARCHAR(120) NOT NULL UNIQUE,
    `type` VARCHAR(32) NOT NULL,
    `webhook_token` VARCHAR(64) NOT NULL UNIQUE,
    `default_cluster` VARCHAR(255),
    `default_namespace` VARCHAR(255),
    `auto_analyze` BOOL NOT NULL,
    `enabled` BOOL NOT NULL,
    `received_count` INT NOT NULL,
    `last_received_at` DATETIME(6)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `analysis_model_configs` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `name` VARCHAR(120) NOT NULL,
    `provider` VARCHAR(32) NOT NULL,
    `base_url` VARCHAR(500) NOT NULL,
    `model_name` VARCHAR(120) NOT NULL,
    `secret_ref` LONGTEXT,
    `enabled` BOOL NOT NULL,
    `last_test_status` VARCHAR(32),
    `last_test_message` LONGTEXT,
    `last_tested_at` DATETIME(6)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `datasource_configs` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `name` VARCHAR(120) NOT NULL UNIQUE,
    `type` VARCHAR(32) NOT NULL,
    `base_url` VARCHAR(500) NOT NULL,
    `secret_ref` LONGTEXT,
    `settings` JSON NOT NULL,
    `enabled` BOOL NOT NULL,
    `last_test_status` VARCHAR(32),
    `last_tested_at` DATETIME(6),
    KEY `idx_datasource__type_ef9a04` (`type`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `incidents` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `aggregation_key` VARCHAR(500) NOT NULL,
    `title` VARCHAR(500) NOT NULL,
    `service` VARCHAR(255) NOT NULL,
    `cluster` VARCHAR(255),
    `namespace` VARCHAR(255),
    `severity` VARCHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `started_at` DATETIME(6) NOT NULL,
    `ended_at` DATETIME(6),
    `alert_count` INT NOT NULL,
    KEY `idx_incidents_aggrega_0a5cb4` (`aggregation_key`),
    KEY `idx_incidents_service_70971b` (`service`),
    KEY `idx_incidents_status_396257` (`status`),
    KEY `idx_incidents_started_96cbe7` (`started_at`),
    KEY `idx_incidents_status_a459fb` (`status`, `started_at`),
    KEY `idx_incidents_service_e667d8` (`service`, `started_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `alert_events` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `source` VARCHAR(32) NOT NULL,
    `external_id` VARCHAR(255),
    `fingerprint` VARCHAR(64) NOT NULL,
    `alert_name` VARCHAR(255) NOT NULL,
    `service` VARCHAR(255) NOT NULL,
    `cluster` VARCHAR(255),
    `namespace` VARCHAR(255),
    `instance` VARCHAR(255),
    `severity` VARCHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `started_at` DATETIME(6) NOT NULL,
    `ended_at` DATETIME(6),
    `labels` JSON NOT NULL,
    `annotations` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `incident_id` VARCHAR(40) NOT NULL,
    UNIQUE KEY `uid_alert_event_fingerp_035aab` (`fingerprint`, `started_at`),
    CONSTRAINT `fk_alert_ev_incident_90a09d06` FOREIGN KEY (`incident_id`) REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    KEY `idx_alert_event_inciden_c96e4f` (`incident_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `analysis_runs` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `status` VARCHAR(32) NOT NULL,
    `current_step` VARCHAR(64),
    `progress` DOUBLE NOT NULL,
    `model_name` VARCHAR(120) NOT NULL,
    `investigation_plan` JSON,
    `error_code` VARCHAR(120),
    `error_message` LONGTEXT,
    `input_tokens` INT NOT NULL,
    `output_tokens` INT NOT NULL,
    `started_at` DATETIME(6),
    `completed_at` DATETIME(6),
    `created_at` DATETIME(6) NOT NULL,
    `incident_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_analysis_incident_9a5bfef9` FOREIGN KEY (`incident_id`) REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    KEY `idx_analysis_ru_status_45859f` (`status`),
    KEY `idx_analysis_ru_inciden_5f532f` (`incident_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigations` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `title` VARCHAR(500) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `current_step` VARCHAR(120),
    `progress` DOUBLE NOT NULL,
    `model_name` VARCHAR(120),
    `summary` LONGTEXT,
    `input_tokens` INT NOT NULL,
    `output_tokens` INT NOT NULL,
    `tool_count` INT NOT NULL,
    `error_code` VARCHAR(120),
    `error_message` LONGTEXT,
    `share_token` VARCHAR(64) UNIQUE,
    `started_at` DATETIME(6),
    `completed_at` DATETIME(6),
    `incident_id` VARCHAR(40),
    CONSTRAINT `fk_investig_incident_ef0997cd` FOREIGN KEY (`incident_id`) REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    KEY `idx_investigati_status_189c9e` (`status`),
    KEY `idx_investigati_status_627ef4` (`status`, `created_at`),
    KEY `idx_investigati_inciden_7b8625` (`incident_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigation_events` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `event_type` VARCHAR(64) NOT NULL,
    `payload` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `investigation_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_investig_investig_c71a79c1` FOREIGN KEY (`investigation_id`) REFERENCES `investigations` (`id`) ON DELETE CASCADE,
    KEY `idx_investigati_investi_519aa4` (`investigation_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigation_hypotheses` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `cause` LONGTEXT NOT NULL,
    `confidence` DOUBLE NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `supporting_evidence_ids` JSON NOT NULL,
    `contradicting_evidence_ids` JSON NOT NULL,
    `missing_evidence` JSON NOT NULL,
    `investigation_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_investig_investig_b87bf5fa` FOREIGN KEY (`investigation_id`) REFERENCES `investigations` (`id`) ON DELETE CASCADE,
    KEY `idx_investigati_investi_2b8e83` (`investigation_id`, `confidence`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigation_messages` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `role` VARCHAR(24) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `model_name` VARCHAR(120),
    `tool_calls` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `investigation_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_investig_investig_23e13cec` FOREIGN KEY (`investigation_id`) REFERENCES `investigations` (`id`) ON DELETE CASCADE,
    KEY `idx_investigati_investi_c2240f` (`investigation_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigation_steps` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `sequence` INT NOT NULL,
    `name` VARCHAR(120) NOT NULL,
    `source` VARCHAR(40) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `description` LONGTEXT,
    `parameters` JSON NOT NULL,
    `result_count` INT NOT NULL,
    `duration_ms` INT NOT NULL,
    `error_code` VARCHAR(120),
    `created_at` DATETIME(6) NOT NULL,
    `completed_at` DATETIME(6),
    `investigation_id` VARCHAR(40) NOT NULL,
    UNIQUE KEY `uid_investigati_investi_b553cc` (`investigation_id`, `sequence`),
    CONSTRAINT `fk_investig_investig_61fb8d80` FOREIGN KEY (`investigation_id`) REFERENCES `investigations` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `investigation_evidence` (
    `id` VARCHAR(48) NOT NULL PRIMARY KEY,
    `source` VARCHAR(40) NOT NULL,
    `title` VARCHAR(500) NOT NULL,
    `summary` LONGTEXT NOT NULL,
    `observed_at` DATETIME(6),
    `subject` JSON NOT NULL,
    `values` JSON NOT NULL,
    `quality` DOUBLE NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `investigation_id` VARCHAR(40) NOT NULL,
    `step_id` VARCHAR(40),
    CONSTRAINT `fk_investig_investig_b0f619ae` FOREIGN KEY (`investigation_id`) REFERENCES `investigations` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_investig_investig_b9057110` FOREIGN KEY (`step_id`) REFERENCES `investigation_steps` (`id`) ON DELETE CASCADE,
    KEY `idx_investigati_investi_41c2e9` (`investigation_id`, `created_at`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `root_cause_reports` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `status` VARCHAR(32) NOT NULL,
    `summary` LONGTEXT NOT NULL,
    `confidence` DOUBLE NOT NULL,
    `hypotheses` JSON NOT NULL,
    `recommended_actions` JSON NOT NULL,
    `missing_evidence` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `analysis_run_id` VARCHAR(40) NOT NULL UNIQUE,
    CONSTRAINT `fk_root_cau_analysis_b19927a8` FOREIGN KEY (`analysis_run_id`) REFERENCES `analysis_runs` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `tool_executions` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `source` VARCHAR(32) NOT NULL,
    `query_pack` VARCHAR(64) NOT NULL,
    `template_id` VARCHAR(120) NOT NULL,
    `parameters` JSON NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `duration_ms` INT NOT NULL,
    `result_count` INT NOT NULL,
    `result_summary` JSON,
    `error_code` VARCHAR(120),
    `created_at` DATETIME(6) NOT NULL,
    `analysis_run_id` VARCHAR(40) NOT NULL,
    UNIQUE KEY `uid_tool_execut_analysi_86e2be` (`analysis_run_id`, `template_id`),
    CONSTRAINT `fk_tool_exe_analysis_3b8fcd3a` FOREIGN KEY (`analysis_run_id`) REFERENCES `analysis_runs` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `evidence_items` (
    `id` VARCHAR(48) NOT NULL PRIMARY KEY,
    `type` VARCHAR(64) NOT NULL,
    `source` VARCHAR(32) NOT NULL,
    `title` VARCHAR(500) NOT NULL,
    `summary` LONGTEXT NOT NULL,
    `observed_at` DATETIME(6),
    `subject` JSON NOT NULL,
    `values` JSON NOT NULL,
    `quality` DOUBLE NOT NULL,
    `content_hash` VARCHAR(64) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `analysis_run_id` VARCHAR(40) NOT NULL,
    `tool_execution_id` VARCHAR(40),
    UNIQUE KEY `uid_evidence_it_analysi_30fe56` (`analysis_run_id`, `content_hash`),
    CONSTRAINT `fk_evidence_analysis_641dbcac` FOREIGN KEY (`analysis_run_id`) REFERENCES `analysis_runs` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_evidence_tool_exe_b65b3fbb` FOREIGN KEY (`tool_execution_id`) REFERENCES `tool_executions` (`id`) ON DELETE CASCADE,
    KEY `idx_evidence_it_analysi_e97ea0` (`analysis_run_id`, `type`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `user_feedback` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `verdict` VARCHAR(32) NOT NULL,
    `actual_root_cause` LONGTEXT,
    `comment` LONGTEXT,
    `created_at` DATETIME(6) NOT NULL,
    `report_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_user_fee_root_cau_97e792b1` FOREIGN KEY (`report_id`) REFERENCES `root_cause_reports` (`id`) ON DELETE CASCADE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "3/P5h5jbg="
)
