from pathlib import Path

_ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

import logging
import os
import sys

# Model configuration
# 分别配置 LLM 和 Embedding 的模型类型，支持独立选择
LLM_TYPE = "openai"  # "ollama" or "openai"
EMBED_TYPE = "ollama"  # "ollama" or "openai"

# Ollama settings
OLLAMA_LLM_MODEL = ""
OLLAMA_EMBED_MODEL = ""

# OpenAI settings
OPENAI_LLM_MODEL = ""
OPENAI_EMBED_MODEL = ""
OPENAI_API_KEY = ""
OPENAI_BASE_URL = ""

# 当前生效的模型（根据类型自动选择）
LLM_MODEL = OPENAI_LLM_MODEL if LLM_TYPE == "openai" else OLLAMA_LLM_MODEL
EMBED_MODEL = OPENAI_EMBED_MODEL if EMBED_TYPE == "openai" else OLLAMA_EMBED_MODEL

PYTHON_EXE = os.environ.get(
    "PYTHON_EXE",
    r"C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe",
)

# Text chunking
CHUNK_SIZE = 800
CHUNK_OVERLAP = 50

# Line-based chunking
CHUNK_LINES = 10
CHUNK_LINE_OVERLAP = 3

# Embedding batching
EMBED_BATCH_SIZE = 15
EMBED_MAX_RETRIES = 3
EMBED_TIMEOUT = 300

TEMPERATURE = 0.5

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# Retrieval thresholds
SIMILARITY_THRESHOLD = 1.0
SOFT_REJECTION_THRESHOLD = 2.0
RETRIEVE_TOP_K = 3
REJECTION_MESSAGE = "未在原著中找到相关内容，无法作答"
SOFT_REJECTION_MESSAGE = "⚠️ 原著中未找到高度相关的内容，以下回答基于有限信息"

# Prompt length guards to avoid overloading Ollama.
MAX_CHUNK_CHARS = 900
MAX_PROMPT_CHARS = 3200

# Multi-turn conversation settings
MAX_CONVERSATION_TURNS = 3  # Number of conversation turns to keep in context


def setup_logging() -> None:
    """Configure root logging once. Honors LOG_LEVEL (default INFO)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        stream=sys.stderr,
        force=True,
    )
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
