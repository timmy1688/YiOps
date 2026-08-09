import json
from typing import Any


def estimate_tokens(value: object) -> int:
    """Conservative multilingual token estimate without provider-specific tokenizers."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return max(1, len(text.encode("utf-8")) // 3)


def compact_context(context: dict[str, object], *, max_tokens: int) -> dict[str, object]:
    compacted = _bounded_value(context)
    if not isinstance(compacted, dict):
        compacted = {}
    raw_memories = compacted.get("retrieved_memory", [])
    raw_incidents = compacted.get("recent_incidents", [])
    memories = list(raw_memories) if isinstance(raw_memories, list) else []
    incidents = list(raw_incidents) if isinstance(raw_incidents, list) else []
    while estimate_tokens(compacted) > max_tokens and memories:
        memories.pop()
        compacted["retrieved_memory"] = memories
    while estimate_tokens(compacted) > max_tokens and incidents:
        incidents.pop()
        compacted["recent_incidents"] = incidents
    if estimate_tokens(compacted) > max_tokens:
        compacted = {
            "scope": compacted.get("scope"),
            "incident": compacted.get("incident"),
            "context_policy": {"truncated": True, "max_tokens": max_tokens},
        }
    return compacted


def compact_tool_result(result: dict[str, Any], *, max_chars: int = 12000) -> dict[str, Any]:
    serialized = json.dumps(result, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return result
    return {
        "name": result.get("name"),
        "status": result.get("status"),
        "result_count": result.get("result_count", 0),
        "duration_ms": result.get("duration_ms", 0),
        "parameters": result.get("parameters", {}),
        "error_code": result.get("error_code"),
        "data": {
            "truncated": True,
            "preview": serialized[:max_chars],
        },
    }


def fit_react_context(
    *,
    incident: dict[str, Any],
    evidence: list[dict[str, Any]],
    collection_summary: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    used_packs: list[str],
    max_tokens: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "incident": _bounded_value(incident),
        "used_query_packs": used_packs,
        "collection_summary": collection_summary[-20:],
        "evidence": [],
        "retrieved_memory": [],
    }
    reserve = max(1000, max_tokens // 8)
    budget = max_tokens - reserve
    if estimate_tokens(payload) > budget:
        payload["incident"] = _bounded_value(
            incident,
            max_string=max(200, budget // 4),
            max_items=20,
        )
    for item in memories:
        bounded = _bounded_value(item)
        candidate = {**payload, "retrieved_memory": [*payload["retrieved_memory"], bounded]}
        if estimate_tokens(candidate) > budget:
            break
        payload["retrieved_memory"].append(bounded)
    for item in evidence:
        bounded = _bounded_value(item)
        candidate = {**payload, "evidence": [*payload["evidence"], bounded]}
        if estimate_tokens(candidate) > budget:
            break
        payload["evidence"].append(bounded)
    payload["context_policy"] = {
        "max_tokens": max_tokens,
        "estimated_tokens": estimate_tokens(payload),
        "evidence_included": len(payload["evidence"]),
        "memory_chunks_included": len(payload["retrieved_memory"]),
        "truncated": len(payload["evidence"]) < len(evidence)
        or len(payload["retrieved_memory"]) < len(memories),
    }
    return payload


def _bounded_value(
    value: Any,
    *,
    depth: int = 0,
    max_string: int = 4000,
    max_items: int = 50,
) -> Any:
    if depth >= 5:
        return str(value)[: min(500, max_string)]
    if isinstance(value, str):
        return value[:max_string]
    if isinstance(value, dict):
        return {
            str(key)[:200]: _bounded_value(
                item,
                depth=depth + 1,
                max_string=max_string,
                max_items=max_items,
            )
            for key, item in list(value.items())[:max_items]
        }
    if isinstance(value, list):
        return [
            _bounded_value(
                item,
                depth=depth + 1,
                max_string=max_string,
                max_items=max_items,
            )
            for item in value[:max_items]
        ]
    return value
