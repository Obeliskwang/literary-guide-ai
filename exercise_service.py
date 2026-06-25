"""练习题服务模块"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_exercises_data(file_name="exercises.json"):
    """加载练习题数据

    Args:
        file_name: 题库文件名

    Returns:
        包含题库数据的字典
    """
    file_path = DATA_DIR / file_name
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Loaded exercises data from {file_path}")
        return data
    except FileNotFoundError:
        logger.error(f"Exercises data file not found: {file_path}")
        return {"book": "", "exercises": []}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse exercises data: {e}")
        return {"book": "", "exercises": []}


def get_exercises():
    """获取所有练习题列表"""
    data = load_exercises_data()
    return data.get("exercises", [])


def get_exercise_by_id(exercise_id):
    """根据ID获取练习题

    Args:
        exercise_id: 题目ID

    Returns:
        题目字典，若不存在返回None
    """
    exercises = get_exercises()
    for exercise in exercises:
        if exercise.get("id") == exercise_id:
            return exercise
    return None


def get_exercises_by_chapter(chapter):
    """按章节获取练习题

    Args:
        chapter: 章节名称

    Returns:
        该章节下的所有题目列表
    """
    exercises = get_exercises()
    return [e for e in exercises if e.get("chapter") == chapter]


def get_all_chapters():
    """获取所有章节列表"""
    exercises = get_exercises()
    chapters = []
    seen = set()
    for exercise in exercises:
        chapter = exercise.get("chapter")
        if chapter and chapter not in seen:
            chapters.append(chapter)
            seen.add(chapter)
    return chapters


def get_book_title():
    """获取书籍名称"""
    data = load_exercises_data()
    return data.get("book", "")


def get_total_count():
    """获取题目总数"""
    exercises = get_exercises()
    return len(exercises)


def get_exercises_by_difficulty(difficulty):
    """按难度获取练习题

    Args:
        difficulty: 难度等级 easy/medium/hard

    Returns:
        该难度下的所有题目列表
    """
    exercises = get_exercises()
    return [e for e in exercises if e.get("difficulty") == difficulty]
