"""人物关系服务模块"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"


def escape_mermaid_text(text: str) -> str:
    """转义 Mermaid 特殊字符"""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("<", "&lt;")  # 新增：转义 <
        .replace(">", "&gt;")  # 新增：转义 >
    )


def load_characters_data(book_name=None):
    """加载人物关系数据

    Args:
        book_name: 书籍名称，传入时生成文件名 characters_{book_name}.json
                   不传时使用默认文件名 characters.json（保持向后兼容）

    Returns:
        包含人物关系数据的字典
    """
    if book_name:
        file_name = f"characters_{book_name}.json"
    else:
        file_name = "characters.json"

    file_path = DATA_DIR / file_name
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded character data from {file_path}")
        return data
    except FileNotFoundError:
        logger.error(f"Character data file not found: {file_path}")
        return {"book": book_name or "", "characters": [], "relations": []}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse character data: {e}")
        return {"book": book_name or "", "characters": [], "relations": []}


def get_characters(book_name=None):
    """获取所有人物列表

    Args:
        book_name: 书籍名称

    Returns:
        人物列表
    """
    data = load_characters_data(book_name)
    return data.get("characters", [])


def get_character_by_id(char_id, book_name=None):
    """根据ID获取人物信息

    Args:
        char_id: 人物ID
        book_name: 书籍名称

    Returns:
        人物字典，若不存在返回None
    """
    characters = get_characters(book_name)
    for char in characters:
        if char.get("id") == char_id:
            return char
    return None


def get_relations(book_name=None):
    """获取所有关系列表

    Args:
        book_name: 书籍名称

    Returns:
        关系列表
    """
    data = load_characters_data(book_name)
    return data.get("relations", [])


def get_book_title(book_name=None):
    """获取书籍名称

    Args:
        book_name: 书籍名称

    Returns:
        书籍名称字符串
    """
    data = load_characters_data(book_name)
    return data.get("book", book_name or "")


def get_character_relations(char_id, book_name=None):
    """获取某个人物的所有关系

    Args:
        char_id: 人物ID
        book_name: 书籍名称

    Returns:
        关系列表
    """
    relations = get_relations(book_name)
    characters = get_characters(book_name)

    result = []
    char_name_map = {c["id"]: c["name"] for c in characters}

    for rel in relations:
        if rel["from"] == char_id:
            result.append(
                {
                    "target_id": rel["to"],
                    "target_name": char_name_map.get(rel["to"], "未知"),
                    "relation": rel["relation"],
                    "type": rel["type"],
                }
            )
        elif rel["to"] == char_id:
            result.append(
                {
                    "target_id": rel["from"],
                    "target_name": char_name_map.get(rel["from"], "未知"),
                    "relation": rel["relation"],
                    "type": rel["type"],
                }
            )

    return result


def generate_mermaid_graph(main_char_id=None, book_name=None):
    """生成 Mermaid 关系图代码

    Args:
        main_char_id: 主要人物ID（可选），传入时只显示相关人物和关系
        book_name: 书籍名称

    Returns:
        Mermaid 图表代码字符串
    """
    characters = get_characters(book_name)
    relations = get_relations(book_name)

    if main_char_id:
        filtered_relations = []
        for rel in relations:
            if rel["from"] == main_char_id or rel["to"] == main_char_id:
                filtered_relations.append(rel)
        relations = filtered_relations
        related_char_ids = {main_char_id}
        for rel in relations:
            related_char_ids.add(rel["from"])
            related_char_ids.add(rel["to"])
        characters = [c for c in characters if c["id"] in related_char_ids]

    # 使用列表收集所有行
    lines = ["graph TD"]  # 第一行
    char_map = {}

    # 生成节点 - 每个节点独占一行，带缩进
    for idx, char in enumerate(characters):
        nid = f"N{idx}"
        char_map[char["id"]] = nid
        name = escape_mermaid_text(char["name"])
        identity = escape_mermaid_text(char["identity"])
        lines.append(f"    {nid}[{name}<br/>{identity}]")  # 添加缩进

    # 生成连线 - 每个连线独占一行，带缩进
    for rel in relations:
        f_node = char_map.get(rel["from"])
        t_node = char_map.get(rel["to"])
        rel_name = escape_mermaid_text(rel["relation"])
        if f_node and t_node:
            lines.append(f"    {f_node} -->|{rel_name}| {t_node}")  # 添加缩进

    # 用换行符连接所有行
    mermaid_code = "\n".join(lines)

    # 确保以换行结尾
    if not mermaid_code.endswith("\n"):
        mermaid_code += "\n"

    return mermaid_code


def generate_mermaid_graph_family(book_name=None):
    """生成主要角色关系图

    Args:
        book_name: 书籍名称

    Returns:
        Mermaid 图表代码字符串
    """
    characters = get_characters(book_name)
    relations = get_relations(book_name)

    # 获取主要角色
    main_chars = [c for c in characters if c.get("role") == "主要角色"]

    # 获取与主要角色相关的关系
    main_char_ids = [c["id"] for c in main_chars]
    team_relations = []
    for rel in relations:
        if rel["from"] in main_char_ids and rel["to"] in main_char_ids:
            team_relations.append(rel)

    # 用列表存储每一行，天然隔离换行，不会粘连
    mermaid_lines = []
    char_map = {}

    # 生成节点（每行一条）
    for idx, char in enumerate(main_chars):
        nid = f"N{idx}"
        char_map[char["id"]] = nid
        name = escape_mermaid_text(char["name"])
        identity = escape_mermaid_text(char["identity"])
        # 节点内换行只用<br/>
        line = f"{nid}[{name}<br/>{identity}]"
        mermaid_lines.append(line)

    # 生成连线（每行一条）
    for rel in team_relations:
        f_node = char_map.get(rel["from"])
        t_node = char_map.get(rel["to"])
        rel_name = escape_mermaid_text(rel["relation"])
        if f_node and t_node:
            line = f"{f_node} -->|{rel_name}| {t_node}"
            mermaid_lines.append(line)

    # 统一拼接，每行强制分割，graph TD 单独一行
    mermaid_code = "graph TD\n" + "\n".join(mermaid_lines)
    return mermaid_code


def get_characters_by_family(family_name, book_name=None):
    """按家族筛选人物

    Args:
        family_name: 家族名称
        book_name: 书籍名称

    Returns:
        该家族的人物列表
    """
    characters = get_characters(book_name)
    return [c for c in characters if c.get("family") == family_name]


def get_all_families(book_name=None):
    """获取所有家族列表

    Args:
        book_name: 书籍名称

    Returns:
        家族名称列表（已排序）
    """
    characters = get_characters(book_name)
    families = set()
    for char in characters:
        family = char.get("family")
        if family:
            families.add(family)
    return sorted(list(families))


def get_events(book_name=None):
    """获取所有核心事件列表

    Args:
        book_name: 书籍名称

    Returns:
        事件列表
    """
    data = load_characters_data(book_name)
    return data.get("events", [])


def get_character_events(char_id, book_name=None):
    """获取某个人物参与的所有事件

    Args:
        char_id: 人物ID
        book_name: 书籍名称

    Returns:
        事件列表
    """
    data = load_characters_data(book_name)
    character_events = data.get("character_events", [])
    events = data.get("events", [])

    # 建立事件ID到事件的映射
    event_map = {e["id"]: e for e in events}

    # 查找该人物参与的事件
    char_events = []
    for ce in character_events:
        if ce.get("character_id") == char_id:
            for event_id in ce.get("events", []):
                if event_id in event_map:
                    char_events.append(event_map[event_id])

    return char_events


def get_event_by_id(event_id, book_name=None):
    """根据事件ID获取事件详情

    Args:
        event_id: 事件ID
        book_name: 书籍名称

    Returns:
        事件字典，若不存在返回None
    """
    events = get_events(book_name)
    for event in events:
        if event.get("id") == event_id:
            return event
    return None