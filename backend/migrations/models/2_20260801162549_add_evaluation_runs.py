from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `evaluation_runs` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `benchmark` VARCHAR(120) NOT NULL,
    `engine` VARCHAR(120) NOT NULL,
    `scenario_count` INT NOT NULL,
    `aggregate` JSON NOT NULL,
    `categories` JSON NOT NULL,
    `results` JSON NOT NULL,
    `duration_ms` INT NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `tenant_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_evaluati_tenants_416b4d59` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
    KEY `idx_evaluation__tenant__748026` (`tenant_id`, `created_at`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `evaluation_runs`;"""


MODELS_STATE = (
    "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"
)
