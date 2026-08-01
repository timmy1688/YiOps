from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.config import Settings
from app.llm import deepseek
from app.llm.deepseek import DeepSeekClient, ModelRuntime
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


@pytest.mark.asyncio
async def test_chat_includes_yiops_context_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Completions:
        async def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="  分析结果  "))],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4),
            )

    client = DeepSeekClient(Settings())

    async def runtime() -> ModelRuntime:
        model_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        return ModelRuntime(
            client=cast(Any, model_client),
            model_name="chat-model",
            is_local=False,
        )

    monkeypatch.setattr(client, "runtime", runtime)
    result = await client.chat(
        [{"role": "user", "content": "发生了什么？"}],
        {"scope": "incident", "incident": {"title": "CPU 告警"}},
    )

    assert result.content == "分析结果"
    assert result.model_name == "chat-model"
    assert result.input_tokens == 12
    assert captured["messages"][1] == {"role": "user", "content": "发生了什么？"}
    assert "<yiops_context>" in captured["messages"][0]["content"]
    assert "CPU 告警" in captured["messages"][0]["content"]


@pytest.mark.asyncio
async def test_chat_local_mode_explains_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DeepSeekClient(Settings())

    async def runtime() -> ModelRuntime:
        return ModelRuntime(client=None, model_name="local-evidence-rules", is_local=True)

    monkeypatch.setattr(client, "runtime", runtime)
    result = await client.chat(
        [{"role": "user", "content": "帮我分析"}],
        {"scope": "overview"},
    )

    assert "分析模型" in result.content
    assert result.model_name == "local-evidence-rules"


@pytest.mark.asyncio
async def test_chat_executes_datasource_tool_and_returns_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []

    class Completions:
        async def create(self, **kwargs: Any) -> Any:
            requests.append(kwargs)
            if len(requests) == 1:
                tool_call = SimpleNamespace(
                    id="call-1",
                    function=SimpleNamespace(
                        name="query_loki_logs",
                        arguments='{"query":"{namespace=~\\".+\\"}","limit":10}',
                    ),
                )
                message = SimpleNamespace(content=None, tool_calls=[tool_call])
                message.model_dump = lambda **_kwargs: {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "query_loki_logs",
                                "arguments": tool_call.function.arguments,
                            },
                        }
                    ],
                }
            else:
                message = SimpleNamespace(content="找到 10 条 Loki 日志", tool_calls=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message)],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

    client = DeepSeekClient(Settings())

    async def runtime() -> ModelRuntime:
        model_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        return ModelRuntime(
            client=cast(Any, model_client),
            model_name="tool-model",
            is_local=False,
        )

    executed: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, arguments))
        return {
            "name": name,
            "status": "completed",
            "result_count": 10,
            "duration_ms": 12,
            "parameters": arguments,
            "error_code": None,
            "data": {"entries": [{"line": "hello"}]},
        }

    monkeypatch.setattr(client, "runtime", runtime)
    result = await client.chat(
        [{"role": "user", "content": "查询最近 10 条 Loki 日志"}],
        {"scope": "overview"},
        tools=[{"type": "function", "function": {"name": "query_loki_logs"}}],
        tool_executor=execute_tool,
    )

    assert result.content == "找到 10 条 Loki 日志"
    assert executed[0][0] == "query_loki_logs"
    assert executed[0][1]["limit"] == 10
    assert result.tool_calls[0]["result_count"] == 10
    assert "data" not in result.tool_calls[0]
    assert requests[1]["messages"][-1]["role"] == "tool"
