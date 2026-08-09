from collections.abc import Sequence
from typing import Any, cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatResult as LangChainChatResult
from langchain_core.runnables import Runnable

from app.agents.conversation import ConversationAgent
from app.config import Settings
from app.llm.gateway import ModelRuntime


class RuntimeGateway:
    def __init__(self, runtime: ModelRuntime) -> None:
        self.value = runtime

    async def runtime(self) -> ModelRuntime:
        return self.value


class ToolCallingModel(BaseChatModel):
    responses: list[AIMessage]
    response_index: int = 0

    @property
    def _llm_type(self) -> str:
        return "yiops-test-tool-model"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        return self.bind(tools=tools)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> LangChainChatResult:
        message = self.responses[self.response_index]
        self.response_index = min(self.response_index + 1, len(self.responses) - 1)
        return LangChainChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> LangChainChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def agent_with_model(
    model: BaseChatModel, settings: Settings | None = None
) -> ConversationAgent:
    runtime = ModelRuntime(
        model=model,
        model_name="framework-model",
        is_local=False,
    )
    agent = ConversationAgent(settings or Settings(), cast(Any, RuntimeGateway(runtime)))
    return agent


@pytest.mark.asyncio
async def test_langchain_agent_runs_tool_loop_and_returns_audit() -> None:
    model = ToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_prometheus",
                        "args": {"query": "up", "minutes": 15},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Prometheus 显示实例在线。"),
        ]
    )
    executed: list[tuple[str, dict[str, Any]]] = []

    async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        executed.append((name, arguments))
        return {
            "name": name,
            "status": "completed",
            "result_count": 1,
            "duration_ms": 8,
            "parameters": arguments,
            "error_code": None,
            "data": {"series": [{"metric": {"job": "api"}, "values": []}]},
        }

    result = await agent_with_model(model).run(
        [{"role": "user", "content": "检查实例"}],
        {
            "scope": "overview",
            "available_datasources": [{"type": "prometheus"}],
        },
        tool_executor=execute,
    )

    assert executed == [
        (
            "query_prometheus",
            {"query": "up", "minutes": 15, "step_seconds": 30},
        )
    ]
    assert result.content == "Prometheus 显示实例在线。"
    assert result.tool_calls == [
        {
            "name": "query_prometheus",
            "status": "completed",
            "result_count": 1,
            "duration_ms": 8,
            "parameters": {"query": "up", "minutes": 15, "step_seconds": 30},
            "error_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_tool_executor_retries_once_without_duplicate_audit() -> None:
    model = ToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_prometheus",
                        "args": {"query": "up"},
                        "id": "call-retry",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="重试后查询成功。"),
        ]
    )
    attempts = 0

    async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary timeout")
        return {
            "name": name,
            "status": "completed",
            "result_count": 1,
            "duration_ms": 12,
            "parameters": arguments,
            "error_code": None,
            "data": {},
        }

    result = await agent_with_model(model).run(
        [{"role": "user", "content": "检查实例"}],
        {
            "scope": "overview",
            "available_datasources": [{"type": "prometheus"}],
        },
        tool_executor=execute,
    )

    assert attempts == 2
    assert result.content == "重试后查询成功。"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_langgraph_agent_streams_model_tokens() -> None:
    received: list[str] = []

    async def on_token(token: str) -> None:
        received.append(token)

    result = await agent_with_model(FakeListChatModel(responses=["流式正常"])).run(
        [{"role": "user", "content": "测试流式输出"}],
        {"scope": "overview"},
        token_callback=on_token,
    )

    assert "".join(received) == "流式正常"
    assert result.content == "流式正常"


@pytest.mark.asyncio
async def test_local_mode_returns_configuration_guidance() -> None:
    runtime = ModelRuntime(model=None, model_name="local-evidence-rules", is_local=True)
    agent = ConversationAgent(Settings(), cast(Any, RuntimeGateway(runtime)))

    result = await agent.run(
        [{"role": "user", "content": "帮我分析"}],
        {"scope": "overview"},
    )

    assert "分析模型" in result.content
    assert result.model_name == "local-evidence-rules"
