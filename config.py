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

LLM_MODEL = "llama3.2"
EMBED_MODEL = "mxbai-embed-large"
# VISION_MODEL = "llava"  # 暂时注释掉，项目暂时不需要 llava 模型

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Embedding 批处理配置（解决 502 错误）
EMBED_BATCH_SIZE = 10  # 每批处理的 chunk 数量
EMBED_MAX_RETRIES = 3  # 最大重试次数
EMBED_TIMEOUT = 300  # 单次请求超时（秒）

TEMPERATURE = 0.6

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# RAG检索配置
SIMILARITY_THRESHOLD = 1.5  # 距离阈值，Chroma返回的是距离值，越小越相似，超过此值拒答
RETRIEVE_TOP_K = 5  # 召回段落数
REJECTION_MESSAGE = "未在原著中找到相关内容，无法作答"  # 拒答文案


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
    # Quiet noisy HTTP clients used by Ollama / embeddings
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
