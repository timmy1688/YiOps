import json
from typing import Any


def encode_sse(payload: dict[str, Any]) -> str:
    """Encode one named Server-Sent Event using UTF-8 JSON data."""
    event = str(payload["event"])
    data = json.dumps(payload["data"], ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"
