from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage

from app.agents.tools import available_tool_specs
from app.config import Settings
from app.llm import gateway
from app.llm.gateway import ModelGateway, ModelRuntime
from app.schemas import AnalysisModelConfigUpsert, QueryPackPlan


def test_model_channel_defaults_to_openai_compatible() -> None:
    payload = AnalysisModelConfigUpsert(
        name="Production",
        base_url="https://models.example.com/v1",
        model_name="analysis-model",
        api_key="test-key",
    )

    assert payload.provider == "openai_compatible"


def test_legacy_deepseek_provider_is_still_accepted() -> None:
    payload = AnalysisModelConfigUpsert(
        name="Legacy",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model_name="deepseek-chat",
        api_key="test-key",
    )

    assert payload.provider == "deepseek"


def test_legacy_model_environment_names_remain_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YIOPS_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("YIOPS_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("YIOPS_MODEL_NAME", raising=False)
    monkeypatch.setenv("YIOPS_DEEPSEEK_API_KEY", "legacy-key")
    monkeypatch.setenv("YIOPS_DEEPSEEK_BASE_URL", "https://legacy.example.com/v1")
    monkeypatch.setenv("YIOPS_DEEPSEEK_MODEL", "legacy-model")

    settings = Settings(_env_file=None)

    assert settings.model_api_key == "legacy-key"
    assert settings.model_base_url == "https://legacy.example.com/v1"
    assert settings.model_name == "legacy-model"


@pytest.mark.asyncio
async def test_connection_uses_langchain_openai_compatible_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Model:
        async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
            captured["messages"] = messages
            captured["invoke"] = kwargs
            return AIMessage(content="OK")

    def model_factory(**kwargs: Any) -> Model:
        captured["model"] = kwargs
        return Model()

    monkeypatch.setattr(gateway, "ChatOpenAI", model_factory)

    message = await ModelGateway.test_connection(
        api_key="test-key",
        base_url="https://models.example.com/v1",
        model_name="analysis-model",
    )

    assert message == "模型响应正常：OK"
    assert captured["model"] == {
        "api_key": "test-key",
        "base_url": "https://models.example.com/v1",
        "model": "analysis-model",
        "timeout": 30.0,
        "max_retries": 2,
        "streaming": True,
    }
    assert captured["messages"][0].content.startswith("Reply with exactly OK")
    assert captured["invoke"] == {"max_tokens": 8}


def test_chat_only_exposes_tools_for_configured_datasources() -> None:
    tools = available_tool_specs(
        {
            "available_datasources": [
                {"name": "Prometheus", "type": "prometheus"},
                {"name": "Kubernetes", "type": "kubernetes"},
            ]
        }
    )

    names = {item.name for item in tools}
    assert names == {"get_incident_analysis", "query_prometheus", "inspect_kubernetes"}


@pytest.mark.asyncio
async def test_planning_uses_langchain_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Runnable:
        async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
            captured["messages"] = messages
            return {
                "raw": AIMessage(
                    content='{"query_packs":["service_health"]}',
                    usage_metadata={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12},
                ),
                "parsed": QueryPackPlan(query_packs=["service_health"]),
                "parsing_error": None,
            }

    class Model:
        def with_structured_output(self, schema: type[Any], **kwargs: Any) -> Runnable:
            captured["schema"] = schema
            captured["options"] = kwargs
            return Runnable()

    client = ModelGateway(Settings())

    async def runtime() -> ModelRuntime:
        return ModelRuntime(
            model=cast(Any, Model()),
            model_name="structured-model",
            is_local=False,
        )

    monkeypatch.setattr(client, "runtime", runtime)
    result = await client.plan({"alert_name": "HighLatency"})

    assert result.value.query_packs == ["service_health"]
    assert (result.input_tokens, result.output_tokens) == (9, 3)
    assert captured["schema"] is QueryPackPlan
    assert captured["options"] == {
        "method": "json_mode",
        "include_raw": True,
        "max_tokens": 1000,
    }
    assert "HighLatency" in captured["messages"][1].content
