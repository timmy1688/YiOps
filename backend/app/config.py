from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_prefix="YIOPS_",
        extra="ignore",
    )

    app_name: str = "YiOps"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "mysql://root:root_password@127.0.0.1:3306/yiops?charset=utf8mb4"
    auto_create_tables: bool = True
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    auth_enabled: bool = False
    admin_username: str = "admin"
    admin_password: str = ""
    session_ttl_hours: int = Field(default=168, ge=1, le=720)
    auth_cookie_secure: bool = False

    model_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("YIOPS_MODEL_API_KEY", "YIOPS_DEEPSEEK_API_KEY"),
    )
    model_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("YIOPS_MODEL_BASE_URL", "YIOPS_DEEPSEEK_BASE_URL"),
    )
    model_name: str = Field(
        default="deepseek-v4-pro",
        validation_alias=AliasChoices("YIOPS_MODEL_NAME", "YIOPS_DEEPSEEK_MODEL"),
    )
    datasource_mock_mode: bool = True
    llm_mock_mode: bool = True

    mcp_url: str = "http://127.0.0.1:8110/mcp"
    mcp_internal_token: str = "yiops-local-development-token"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = Field(default=8110, ge=1, le=65535)

    analysis_concurrency: int = Field(default=2, ge=1, le=10)
    analysis_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    datasource_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    max_log_samples: int = Field(default=20, ge=1, le=100)
    max_evidence_items: int = Field(default=30, ge=5, le=100)
    agent_max_context_tokens: int = Field(default=24000, ge=4000, le=128000)
    agent_max_react_rounds: int = Field(default=6, ge=2, le=12)
    chat_max_tool_calls: int = Field(default=8, ge=2, le=20)
    chat_tool_result_chars: int = Field(default=8000, ge=2000, le=20000)
    rag_max_chunks: int = Field(default=6, ge=1, le=20)
    rag_chunk_chars: int = Field(default=1800, ge=500, le=5000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
