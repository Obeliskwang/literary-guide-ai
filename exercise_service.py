"""练习题服务模块"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_exercises_data(book_name=None):
    """加载练习题数据

    Args:
        book_name: 书籍名称，传入时生成文件名 exercises_{book_name}.json
                   不传时使用默认文件名 exercises.json（保持向后兼容）

    Returns:
        包含题库数据的字典
    """
    if book_name:
        file_name = f"exercises_{book_name}.json"
    else:
        file_name = "exercises.json"

    file_path = DATA_DIR / file_name
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded exercises data from {file_path}")
        return data
    except FileNotFoundError:
        logger.error(f"Exercises data file not found: {file_path}")
        return {"book": book_name or "", "exercises": []}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse exercises data: {e}")
        return {"book": book_name or "", "exercises": []}


def get_exercises(book_name=None):
    """获取所有练习题列表

    Args:
        book_name: 书籍名称

    Returns:
        练习题列表
    """
    data = load_exercises_data(book_name)
    return data.get("exercises", [])


def get_exercise_by_id(exercise_id, book_name=None):
    """根据ID获取练习题

    Args:
        exercise_id: 题目ID
        book_name: 书籍名称

    Returns:
        题目字典，若不存在返回None
    """
    exercises = get_exercises(book_name)
    for exercise in exercises:
        if exercise.get("id") == exercise_id:
            return exercise
    return None


def get_exercises_by_chapter(chapter, book_name=None):
    """按章节获取练习题

    Args:
        chapter: 章节名称
        book_name: 书籍名称

    Returns:
        该章节下的所有题目列表
    """
    exercises = get_exercises(book_name)
    return [e for e in exercises if e.get("chapter") == chapter]


def get_all_chapters(book_name=None):
    """获取所有章节列表

    Args:
        book_name: 书籍名称

    Returns:
        章节名称列表
    """
    exercises = get_exercises(book_name)
    chapters = []
    seen = set()
    for exercise in exercises:
        chapter = exercise.get("chapter")
        if chapter and chapter not in seen:
            chapters.append(chapter)
            seen.add(chapter)
    return chapters


def get_book_title(book_name=None):
    """获取书籍名称

    Args:
        book_name: 书籍名称

    Returns:
        书籍名称字符串
    """
    data = load_exercises_data(book_name)
    return data.get("book", book_name or "")


def get_total_count(book_name=None):
    """获取题目总数

    Args:
        book_name: 书籍名称

    Returns:
        题目数量
    """
    exercises = get_exercises(book_name)
    return len(exercises)


def get_exercises_by_difficulty(difficulty, book_name=None):
    """按难度获取练习题

    Args:
        difficulty: 难度等级 easy/medium/hard
        book_name: 书籍名称

    Returns:
        该难度下的所有题目列表
    """
    exercises = get_exercises(book_name)
    return [e for e in exercises if e.get("difficulty") == difficulty]