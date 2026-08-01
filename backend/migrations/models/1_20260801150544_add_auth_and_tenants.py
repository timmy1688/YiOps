from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `investigations` DROP INDEX `idx_investigati_status_627ef4`;
        ALTER TABLE `incidents` DROP INDEX `idx_incidents_service_e667d8`;
        ALTER TABLE `incidents` DROP INDEX `idx_incidents_status_a459fb`;
        ALTER TABLE `datasource_configs` DROP INDEX `name`;
        ALTER TABLE `alert_integrations` DROP INDEX `name`;
        ALTER TABLE `alert_events` DROP INDEX `uid_alert_event_fingerp_035aab`;
CREATE TABLE IF NOT EXISTS `tenants` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `name` VARCHAR(120) NOT NULL,
    `slug` VARCHAR(80) NOT NULL UNIQUE,
    `active` BOOL NOT NULL
) CHARACTER SET utf8mb4;
        INSERT INTO `tenants` (`id`, `name`, `slug`, `active`, `created_at`, `updated_at`)
        VALUES ('tenant_default', 'Default Workspace', 'default', TRUE, NOW(6), NOW(6))
        ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);
        CREATE TABLE IF NOT EXISTS `users` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `username` VARCHAR(120) NOT NULL UNIQUE,
    `display_name` VARCHAR(120) NOT NULL,
    `password_hash` VARCHAR(500) NOT NULL,
    `role` VARCHAR(32) NOT NULL,
    `active` BOOL NOT NULL,
    `last_login_at` DATETIME(6),
    `tenant_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_users_tenants_8ece25af` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
    KEY `idx_users_tenant__8ea61c` (`tenant_id`, `active`)
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `user_sessions` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `token_hash` VARCHAR(64) NOT NULL UNIQUE,
    `csrf_token_hash` VARCHAR(64) NOT NULL,
    `expires_at` DATETIME(6) NOT NULL,
    `last_seen_at` DATETIME(6) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `user_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_user_ses_users_c288d510` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    KEY `idx_user_sessio_expires_9ce72a` (`expires_at`),
    KEY `idx_user_sessio_user_id_599f73` (`user_id`, `expires_at`)
) CHARACTER SET utf8mb4;
        ALTER TABLE `alert_events` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `alert_integrations` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `analysis_model_configs` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `datasource_configs` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `incidents` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `investigations` ADD `tenant_id` VARCHAR(40) NOT NULL DEFAULT 'tenant_default';
        ALTER TABLE `alert_events` ADD CONSTRAINT `fk_alert_ev_tenants_ae18bff9` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `alert_events` ADD UNIQUE INDEX `uid_alert_event_tenant__e63307` (`tenant_id`, `fingerprint`, `started_at`);
        ALTER TABLE `alert_integrations` ADD CONSTRAINT `fk_alert_in_tenants_f875d935` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `alert_integrations` ADD UNIQUE INDEX `uid_alert_integ_tenant__02e6e3` (`tenant_id`, `name`);
        ALTER TABLE `analysis_model_configs` ADD CONSTRAINT `fk_analysis_tenants_33b6f1a6` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `analysis_model_configs` ADD UNIQUE INDEX `uid_analysis_mo_tenant__f44012` (`tenant_id`, `name`);
        ALTER TABLE `datasource_configs` ADD CONSTRAINT `fk_datasour_tenants_8d601de7` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `datasource_configs` ADD UNIQUE INDEX `uid_datasource__tenant__98776f` (`tenant_id`, `name`);
        ALTER TABLE `incidents` ADD CONSTRAINT `fk_incident_tenants_3b362683` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `incidents` ADD INDEX `idx_incidents_tenant__fa6d70` (`tenant_id`, `status`, `started_at`);
        ALTER TABLE `incidents` ADD INDEX `idx_incidents_tenant__932737` (`tenant_id`, `service`);
        ALTER TABLE `investigations` ADD CONSTRAINT `fk_investig_tenants_1922334b` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE;
        ALTER TABLE `investigations` ADD INDEX `idx_investigati_tenant__7e753a` (`tenant_id`, `status`, `created_at`);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `analysis_model_configs` DROP INDEX `uid_analysis_mo_tenant__f44012`;
        ALTER TABLE `analysis_model_configs` DROP FOREIGN KEY `fk_analysis_tenants_33b6f1a6`;
        ALTER TABLE `datasource_configs` DROP INDEX `uid_datasource__tenant__98776f`;
        ALTER TABLE `datasource_configs` DROP FOREIGN KEY `fk_datasour_tenants_8d601de7`;
        ALTER TABLE `alert_integrations` DROP INDEX `uid_alert_integ_tenant__02e6e3`;
        ALTER TABLE `alert_integrations` DROP FOREIGN KEY `fk_alert_in_tenants_f875d935`;
        ALTER TABLE `investigations` DROP INDEX `idx_investigati_tenant__7e753a`;
        ALTER TABLE `investigations` DROP FOREIGN KEY `fk_investig_tenants_1922334b`;
        ALTER TABLE `alert_events` DROP INDEX `uid_alert_event_tenant__e63307`;
        ALTER TABLE `alert_events` DROP FOREIGN KEY `fk_alert_ev_tenants_ae18bff9`;
        ALTER TABLE `incidents` DROP INDEX `idx_incidents_tenant__932737`;
        ALTER TABLE `incidents` DROP INDEX `idx_incidents_tenant__fa6d70`;
        ALTER TABLE `incidents` DROP FOREIGN KEY `fk_incident_tenants_3b362683`;
        ALTER TABLE `incidents` DROP COLUMN `tenant_id`;
        ALTER TABLE `alert_events` DROP COLUMN `tenant_id`;
        ALTER TABLE `investigations` DROP COLUMN `tenant_id`;
        ALTER TABLE `alert_integrations` DROP COLUMN `tenant_id`;
        ALTER TABLE `datasource_configs` DROP COLUMN `tenant_id`;
        ALTER TABLE `analysis_model_configs` DROP COLUMN `tenant_id`;
        DROP TABLE IF EXISTS `user_sessions`;
        DROP TABLE IF EXISTS `users`;
        DROP TABLE IF EXISTS `tenants`;
        ALTER TABLE `incidents` ADD INDEX `idx_incidents_status_a459fb` (`status`, `started_at`);
        ALTER TABLE `incidents` ADD INDEX `idx_incidents_service_e667d8` (`service`, `started_at`);
        ALTER TABLE `alert_events` ADD UNIQUE INDEX `uid_alert_event_fingerp_035aab` (`fingerprint`, `started_at`);
        ALTER TABLE `investigations` ADD INDEX `idx_investigati_status_627ef4` (`status`, `created_at`);
        ALTER TABLE `alert_integrations` ADD UNIQUE INDEX `name` (`name`);
        ALTER TABLE `datasource_configs` ADD UNIQUE INDEX `name` (`name`);"""


MODELS_STATE = (
    "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"
)
