from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.rca import RcaAgent
from app.config import Settings
from app.memory.context import estimate_tokens, fit_react_context
from app.memory.wiki import _dot, _embedding, _split_markdown, _tokens
from app.runtime.events import EventBroker
from app.schemas import ReActDecision


def test_markdown_chunking_respects_headings_and_bounds() -> None:
    content = "# Database\n\n" + "连接池超时。" * 120 + "\n\n# Kubernetes\n\nPod 重启。"

    chunks = _split_markdown(content, 500)

    assert len(chunks) >= 2
    assert chunks[0][0] == "Database"
    assert chunks[-1][0] == "Kubernetes"
    assert all(len(chunk) <= 700 for _, chunk in chunks)


def test_local_memory_vector_prefers_related_text() -> None:
    query = _embedding(_tokens("数据库连接池超时"))
    related = _embedding(_tokens("数据库连接池耗尽导致连接超时"))
    unrelated = _embedding(_tokens("Kubernetes 节点磁盘压力"))

    assert _dot(query, related) > _dot(query, unrelated)


def test_context_budget_compacts_evidence() -> None:
    context = fit_react_context(
        incident={"title": "数据库告警", "annotations": {"description": "告警" * 10000}},
        evidence=[{"id": f"ev_{index}", "summary": "证据" * 1000} for index in range(20)],
        collection_summary=[],
        memories=[{"title": "手册", "excerpt": "知识" * 1000}],
        used_packs=[],
        max_tokens=2000,
    )
    assert context["context_policy"]["truncated"] is True
    assert estimate_tokens(context) <= 2200


def test_react_decision_requires_query_pack() -> None:
    with pytest.raises(ValidationError):
        ReActDecision(action="query", rationale="需要取证")


def test_analysis_graph_contains_bounded_react_loop() -> None:
    memory = SimpleNamespace(retrieve=None)
    agent = RcaAgent(
        Settings(),
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        EventBroker(),
        memory,  # type: ignore[arg-type]
    )
    graph = agent.graph.get_graph()
    edges = {(edge.source, edge.target, edge.conditional) for edge in graph.edges}

    assert ("react", "act", True) in edges
    assert ("act", "react", False) in edges
    assert ("react", "analyze", True) in edges
