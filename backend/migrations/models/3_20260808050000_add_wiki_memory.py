from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `wiki_documents` (
    `created_at` DATETIME(6) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `id` VARCHAR(40) NOT NULL PRIMARY KEY,
    `title` VARCHAR(300) NOT NULL,
    `content` LONGTEXT NOT NULL,
    `tags` JSON NOT NULL,
    `status` VARCHAR(24) NOT NULL,
    `version` INT NOT NULL,
    `chunk_count` INT NOT NULL,
    `tenant_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_wiki_docs_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
    UNIQUE KEY `uid_wiki_docs_tenant_title` (`tenant_id`, `title`),
    KEY `idx_wiki_docs_tenant_status` (`tenant_id`, `status`, `updated_at`),
    KEY `idx_wiki_docs_status` (`status`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `wiki_chunks` (
    `id` VARCHAR(48) NOT NULL PRIMARY KEY,
    `ordinal` INT NOT NULL,
    `heading` VARCHAR(500),
    `content` LONGTEXT NOT NULL,
    `token_count` INT NOT NULL,
    `embedding` JSON NOT NULL,
    `keywords` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    `tenant_id` VARCHAR(40) NOT NULL,
    `document_id` VARCHAR(40) NOT NULL,
    CONSTRAINT `fk_wiki_chunks_tenant` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_wiki_chunks_doc` FOREIGN KEY (`document_id`) REFERENCES `wiki_documents` (`id`) ON DELETE CASCADE,
    UNIQUE KEY `uid_wiki_chunks_doc_ordinal` (`document_id`, `ordinal`),
    KEY `idx_wiki_chunks_tenant_doc` (`tenant_id`, `document_id`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `wiki_chunks`;
DROP TABLE IF EXISTS `wiki_documents`;"""


MODELS_STATE = (
    "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"
    "wREI7Plg779n/ZqjTX"
)
