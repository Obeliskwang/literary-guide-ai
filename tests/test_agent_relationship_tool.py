from unittest.mock import MagicMock
from contextlib import contextmanager
from pathlib import Path

import pytest

from backend.agent_tools import (fallback_arguments, fallback_event_arguments,
                                 is_relationship_graph_request, requested_tool_name,
                                 run_character_lookup_tool, run_event_lookup_tool,
                                 run_relationship_graph_tool)
from backend.contracts import Error
from backend.conversations import Conversations
from backend.business import Business


CHARACTERS = [
    {"id": "sun_wukong", "name": "孙悟空"},
    {"id": "tang_seng", "name": "唐僧"},
]


class FakeBusiness:
    def characters(self, user, book_id, family, page, page_size):
        return {"items": CHARACTERS}

    def graph(self, user, book_id, scope, character_id):
        return {"format": "mermaid", "code": f"graph TD\n    selected[{character_id or 'all'}]\n"}

    def relations(self, user, book_id, character_id):
        return {"items": [{"source_id": character_id, "target_id": "tang_seng", "target_name": "唐僧", "relation": "师徒", "type": "师徒"}]}

    def dataset(self, user, book_id, kind):
        return "西游记", {
            "characters": CHARACTERS,
            "events": [
                {"id": "event_2", "name": "大闹龙宫", "chapter": "第2回", "description": "孙悟空取得定海神针。", "characters": ["sun_wukong"]},
                {"id": "event_3", "name": "大闹天宫", "chapter": "第3回", "description": "孙悟空反抗天庭。", "characters": ["sun_wukong"]},
            ],
            "character_events": [{"character_id": "sun_wukong", "events": ["event_2", "event_3"]}],
        }


def test_relationship_intent_and_character_fallback():
    assert is_relationship_graph_request("给我西游记人物关系图")
    assert not is_relationship_graph_request("孙悟空有什么性格特点")
    assert fallback_arguments("显示孙悟空的关系网", CHARACTERS) == {"character_name": "孙悟空"}
    assert requested_tool_name("贾宝玉的身份是什么") == "lookup_characters"
    assert requested_tool_name("第二回有哪些事件") == "lookup_events"
    assert fallback_event_arguments("查孙悟空第二回的事迹", CHARACTERS) == {"character_name": "孙悟空", "chapter": "第2回"}


def test_relationship_tool_returns_mermaid_for_selected_character():
    call = run_relationship_graph_tool(FakeBusiness(), {"id": 1}, "book", {"character_name": "孙悟空"})
    assert call["name"] == "show_relationship_graph"
    assert call["result"]["format"] == "mermaid"
    assert "sun_wukong" in call["result"]["code"]


def test_relationship_tool_rejects_unknown_model_arguments():
    with pytest.raises(Error) as error:
        run_relationship_graph_tool(FakeBusiness(), {"id": 1}, "book", {"path": "secret"})
    assert error.value.code == "TOOL_ARGUMENT_ERROR"


def test_character_lookup_returns_json_identity_fields():
    call = run_character_lookup_tool(FakeBusiness(), {"id": 1}, "book", {"character_name": "孙悟空"})
    assert call["result"]["format"] == "characters"
    assert call["result"]["items"][0]["id"] == "sun_wukong"
    assert set(call["result"]["items"][0]) == {"id", "name", "identity", "description", "family", "role"}
    assert call["result"]["relations"]["sun_wukong"][0]["target_name"] == "唐僧"


def test_event_lookup_accepts_chinese_chapter_and_character_filter():
    call = run_event_lookup_tool(FakeBusiness(), {"id": 1}, "book", {"chapter": "第二回", "character_name": "孙悟空"})
    assert call["arguments"] == {"chapter": "第2回", "character_name": "孙悟空"}
    assert [row["name"] for row in call["result"]["items"]] == ["大闹龙宫"]


def test_tools_read_real_journey_to_the_west_json():
    class DatasetDB:
        dataset = "西游记"

        @contextmanager
        def tx(self):
            yield object()

        def book(self, db, user, book_id):
            return {"dataset": self.dataset}

    database = DatasetDB()
    business = Business(database, Path(__file__).resolve().parents[1])
    event = run_event_lookup_tool(business, {"id": 1}, "book", {"chapter": "第二回"})
    assert [row["name"] for row in event["result"]["items"]] == ["大闹龙宫"]

    database.dataset = "红楼梦"
    character = run_character_lookup_tool(business, {"id": 1}, "book", {"character_name": "贾宝玉"})
    assert character["result"]["items"][0]["identity"] == "荣国府公子"


def test_conversation_routes_graph_request_to_tool_without_rag():
    adapter = MagicMock()
    adapter.choose_tool.return_value = {"name": "show_relationship_graph", "arguments": {}}
    conversations = Conversations(None, adapter, None, FakeBusiness())
    answer = conversations.relationship_answer({"id": 1}, "book", "给我西游记人物关系图", MagicMock())
    assert answer["tool_calls"][0]["result"]["format"] == "mermaid"
    adapter.answer.assert_not_called()
