from types import SimpleNamespace
from typing import Any

import pytest

from app.llm import deepseek
from app.llm.deepseek import DeepSeekClient
from app.schemas import AnalysisModelConfigUpsert


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


@pytest.mark.asyncio
async def test_connection_uses_only_openai_compatible_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Completions:
        async def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
            )

    def client_factory(**kwargs: Any) -> Any:
        captured["client"] = kwargs
        return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))

    monkeypatch.setattr(deepseek, "AsyncOpenAI", client_factory)

    message = await DeepSeekClient.test_connection(
        api_key="test-key",
        base_url="https://models.example.com/v1",
        model_name="analysis-model",
    )

    assert message == "模型响应正常：OK"
    assert captured["client"] == {
        "api_key": "test-key",
        "base_url": "https://models.example.com/v1",
        "timeout": 30.0,
    }
    assert captured["model"] == "analysis-model"
    assert "extra_body" not in captured
