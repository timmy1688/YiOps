from typing import Any


def score_prediction(scenario: dict[str, Any], prediction: dict[str, Any]) -> dict[str, float]:
    expected = scenario["expected"]
    predicted_cause = str(prediction.get("root_cause", "")).lower()
    keywords = [str(value).lower() for value in expected.get("cause_keywords", [])]
    root_cause_top1 = float(bool(keywords) and any(word in predicted_cause for word in keywords))

    relevant = set(expected.get("relevant_evidence_ids", []))
    cited = set(prediction.get("evidence_ids", []))
    valid_ids = {item["id"] for item in scenario.get("observations", [])}
    true_positive = len(relevant & cited)
    evidence_precision = true_positive / len(cited) if cited else 0.0
    evidence_recall = true_positive / len(relevant) if relevant else 1.0

    cited_sources = {
        item["source"] for item in scenario.get("observations", []) if item["id"] in cited
    }
    required_sources = set(expected.get("required_sources", []))
    source_recall = (
        len(cited_sources & required_sources) / len(required_sources) if required_sources else 1.0
    )

    claims = prediction.get("claims", [])
    unsupported = 0
    for claim in claims:
        claim_evidence = set(claim.get("evidence_ids", []))
        if not claim_evidence or not claim_evidence.issubset(valid_ids):
            unsupported += 1
    unsupported_claim_rate = unsupported / len(claims) if claims else 0.0

    confidence = min(max(float(prediction.get("confidence", 0.0)), 0.0), 1.0)
    brier_score = round((confidence - root_cause_top1) ** 2, 6)
    return {
        "root_cause_top1": root_cause_top1,
        "evidence_precision": evidence_precision,
        "evidence_recall": evidence_recall,
        "source_recall": source_recall,
        "unsupported_claim_rate": unsupported_claim_rate,
        "brier_score": brier_score,
        "latency_ms": float(prediction.get("latency_ms", 0)),
        "tool_calls": float(prediction.get("tool_calls", 0)),
        "tokens": float(prediction.get("tokens", 0)),
    }


def aggregate(scores: list[dict[str, float]]) -> dict[str, float]:
    if not scores:
        return {}
    return {key: round(sum(item[key] for item in scores) / len(scores), 4) for key in scores[0]}
