"""Small, read-only tools used by the literary assistant."""
from __future__ import annotations

import re

from .contracts import Error


RELATIONSHIP_GRAPH_TOOL = {
    "type": "function",
    "function": {
        "name": "show_relationship_graph",
        "description": "在当前书籍的对话中展示人物关系图。用户要求查看人物关系图、关系网或人物图谱时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "character_name": {
                    "type": "string",
                    "description": "可选。只展示该人物及其直接关系；未指定时展示整本书的人物关系图。",
                }
            },
            "additionalProperties": False,
        },
    },
}

CHARACTER_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_characters",
        "description": "查询当前书籍的人物表或指定人物的身份、简介、家族、角色等结构化信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "character_name": {"type": "string", "description": "可选人物姓名；未指定时返回人物表。"}
            },
            "additionalProperties": False,
        },
    },
}

EVENT_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_events",
        "description": "查询当前书籍的事件表，可按回目或人物筛选事件、事迹和情节。",
        "parameters": {
            "type": "object",
            "properties": {
                "chapter": {"type": "string", "description": "可选回目，例如第2回或第二回。"},
                "character_name": {"type": "string", "description": "可选人物姓名。"},
            },
            "additionalProperties": False,
        },
    },
}

AGENT_TOOLS = [RELATIONSHIP_GRAPH_TOOL, CHARACTER_LOOKUP_TOOL, EVENT_LOOKUP_TOOL]


def is_relationship_graph_request(question: str) -> bool:
    """Cheap pre-filter: avoid an extra model request for ordinary RAG questions."""
    compact = re.sub(r"\s+", "", question).casefold()
    return any(word in compact for word in ("人物关系图", "角色关系图", "关系图", "人物图谱", "关系网"))


def requested_tool_name(question: str) -> str | None:
    """Route only explicit business terms; general questions remain on the RAG path."""
    compact = re.sub(r"\s+", "", question).casefold()
    if is_relationship_graph_request(question):
        return "show_relationship_graph"
    if any(word in compact for word in ("事件表", "事件", "事迹", "情节表")):
        return "lookup_events"
    if any(word in compact for word in ("人物表", "人物列表", "人物信息", "角色信息", "人物介绍", "角色介绍", "身份")):
        return "lookup_characters"
    return None


def fallback_arguments(question: str, characters: list[dict]) -> dict:
    """Keep an explicit classroom-demo command usable when a model lacks tool calling."""
    matched = [row for row in characters if row.get("name") and row["name"] in question]
    return {"character_name": matched[0]["name"]} if len(matched) == 1 else {}


_CHINESE_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _chapter_number(value: str) -> int | None:
    text = value.strip().removeprefix("第").removesuffix("回").removesuffix("章")
    if text.isdigit():
        return int(text)
    if not text or any(char not in _CHINESE_DIGITS and char not in "十百" for char in text):
        return None
    total, current = 0, 0
    for char in text:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
    return total + current


def normalize_chapter(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    number = _chapter_number(value)
    return f"第{number}回" if number is not None else value.strip()


def fallback_event_arguments(question: str, characters: list[dict]) -> dict:
    arguments = fallback_arguments(question, characters)
    match = re.search(r"第[零〇一二两三四五六七八九十百\d]+[回章]", question)
    if match:
        arguments["chapter"] = normalize_chapter(match.group(0))
    return arguments


def _validate_arguments(arguments, allowed):
    arguments = arguments if isinstance(arguments, dict) else {}
    if set(arguments) - set(allowed):
        raise Error(422, "TOOL_ARGUMENT_ERROR", "工具参数无效")
    for key, value in arguments.items():
        if value is not None and (not isinstance(value, str) or len(value.strip()) > 100):
            raise Error(422, "TOOL_ARGUMENT_ERROR", f"{key} 参数无效")
    return arguments


def run_relationship_graph_tool(business, user, book_id: str, arguments: dict | None) -> dict:
    """Validate model arguments, resolve a character name, and return display-safe Mermaid."""
    arguments = arguments if isinstance(arguments, dict) else {}
    unknown = set(arguments) - {"character_name"}
    if unknown:
        raise Error(422, "TOOL_ARGUMENT_ERROR", "人物关系图工具参数无效")

    character_name = arguments.get("character_name")
    if character_name is not None and (not isinstance(character_name, str) or len(character_name.strip()) > 100):
        raise Error(422, "TOOL_ARGUMENT_ERROR", "人物名称无效")

    rows = business.characters(user, book_id, None, 1, 100)["items"]
    character = None
    if character_name and character_name.strip():
        name = character_name.strip()
        character = next((row for row in rows if row.get("name") == name), None)
        if character is None:
            raise Error(404, "TOOL_TARGET_NOT_FOUND", f"人物关系数据中没有“{name}”")

    graph = business.graph(user, book_id, "character" if character else "all", character["id"] if character else None)
    return {
        "name": "show_relationship_graph",
        "arguments": {"character_name": character["name"]} if character else {},
        "result": graph,
    }


def run_character_lookup_tool(business, user, book_id: str, arguments: dict | None) -> dict:
    arguments = _validate_arguments(arguments, {"character_name"})
    name = (arguments.get("character_name") or "").strip()
    rows = business.characters(user, book_id, None, 1, 100)["items"]
    if name:
        rows = [row for row in rows if row.get("name") == name]
        if not rows:
            raise Error(404, "TOOL_TARGET_NOT_FOUND", f"人物表中没有“{name}”")
    fields = ("id", "name", "identity", "description", "family", "role")
    items = [{key: row.get(key, "") for key in fields} for row in rows]
    relations = {row["id"]: business.relations(user, book_id, row["id"])["items"] for row in items}
    return {
        "name": "lookup_characters",
        "arguments": {"character_name": name} if name else {},
        "result": {"format": "characters", "items": items, "relations": relations},
    }


def run_event_lookup_tool(business, user, book_id: str, arguments: dict | None) -> dict:
    arguments = _validate_arguments(arguments, {"chapter", "character_name"})
    chapter = normalize_chapter(arguments.get("chapter"))
    character_name = (arguments.get("character_name") or "").strip()
    _, data = business.dataset(user, book_id, "characters")
    characters = data.get("characters", [])
    character = next((row for row in characters if row.get("name") == character_name), None) if character_name else None
    if character_name and character is None:
        raise Error(404, "TOOL_TARGET_NOT_FOUND", f"人物表中没有“{character_name}”")
    rows = data.get("events", [])
    if chapter:
        rows = [row for row in rows if normalize_chapter(row.get("chapter")) == chapter]
    if character:
        mapped_ids = {event_id for row in data.get("character_events", []) if row.get("character_id") == character["id"] for event_id in row.get("events", [])}
        rows = [row for row in rows if character["id"] in row.get("characters", []) or row.get("id") in mapped_ids]
    fields = ("id", "name", "chapter", "description", "characters")
    items = [{key: row.get(key, [] if key == "characters" else "") for key in fields} for row in rows]
    clean_arguments = {}
    if chapter:
        clean_arguments["chapter"] = chapter
    if character:
        clean_arguments["character_name"] = character["name"]
    return {"name": "lookup_events", "arguments": clean_arguments, "result": {"format": "events", "items": items}}
