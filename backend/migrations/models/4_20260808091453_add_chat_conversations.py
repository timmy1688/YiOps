from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `chat_conversations` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `title` VARCHAR(300) NOT NULL,
    `last_message_at` DATETIME(6),
    `incident_id` VARCHAR(40),
    `tenant_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_chat_con_incident_f301eae9` FOREIGN KEY (`incident_id`) REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_chat_con_tenants_026abc4c` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
    KEY `idx_chat_conver_tenant__c4c312` (`tenant_id`, `updated_at`),
    KEY `idx_chat_conver_inciden_10e3db` (`incident_id`, `updated_at`)
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `chat_conversation_messages` (
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `role` VARCHAR(24) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `model_name` VARCHAR(120),
    `tool_calls` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `conversation_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_chat_con_chat_con_0e60d35d` FOREIGN KEY (`conversation_id`) REFERENCES `chat_conversations` (`id`) ON DELETE CASCADE,
    KEY `idx_chat_conver_convers_c3b8b8` (`conversation_id`, `created_at`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `chat_conversation_messages`;
        DROP TABLE IF EXISTS `chat_conversations`;"""


MODELS_STATE = (
    "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"
)
