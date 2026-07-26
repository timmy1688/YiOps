from functools import lru_cache

from pydantic import Field
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

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    datasource_mock_mode: bool = True
    llm_mock_mode: bool = True

    analysis_concurrency: int = Field(default=2, ge=1, le=10)
    analysis_timeout_seconds: int = Field(default=300, ge=30, le=1800)
    datasource_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    max_log_samples: int = Field(default=20, ge=1, le=100)
    max_evidence_items: int = Field(default=30, ge=5, le=100)


@lru_cache
def get_settings() -> Settings:
    return Settings()
