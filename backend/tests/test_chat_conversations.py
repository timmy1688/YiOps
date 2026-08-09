from datetime import UTC, datetime

from app.api.conversations import router
from app.schemas import ChatConversationDetail


def test_chat_conversation_routes_are_registered() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        if hasattr(route, "methods"):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path["/chat/conversations"] == {"GET", "POST"}
    assert "POST" in methods_by_path["/chat/conversations/import"]
    assert "GET" in methods_by_path["/chat/conversations/{conversation_id}"]
    assert "DELETE" in methods_by_path["/chat/conversations/{conversation_id}"]
    assert "POST" in methods_by_path[
        "/chat/conversations/{conversation_id}/messages"
    ]
    assert "POST" in methods_by_path[
        "/chat/conversations/{conversation_id}/messages/stream"
    ]


def test_chat_conversation_detail_keeps_multiple_messages() -> None:
    now = datetime.now(UTC)
    detail = ChatConversationDetail.model_validate(
        {
            "id": "chat_test",
            "title": "磁盘调查",
            "incident_id": None,
            "message_count": 2,
            "last_message_at": now,
            "created_at": now,
            "updated_at": now,
            "messages": [
                {
                    "id": "cmsg_user",
                    "role": "user",
                    "content": "检查磁盘",
                    "model_name": None,
                    "tool_calls": [],
                    "created_at": now,
                },
                {
                    "id": "cmsg_assistant",
                    "role": "assistant",
                    "content": "磁盘压力较高",
                    "model_name": "deepseek-chat",
                    "tool_calls": [],
                    "created_at": now,
                },
            ],
        }
    )

    assert [message.role for message in detail.messages] == ["user", "assistant"]
