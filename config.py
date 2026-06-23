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

LLM_MODEL = "qwen2.5:0.5b-instruct"
EMBED_MODEL = "bge-m3"

# 文本分块配置（基于字符数的分块策略）
CHUNK_SIZE = 800  # 每个chunk的字符数
CHUNK_OVERLAP = 50  # chunk之间的重叠字符数

# 文本分行分块配置
CHUNK_LINES = 50       # 每块多少行，按需调整
CHUNK_LINE_OVERLAP = 8 # 块之间重叠行数

# Embedding 批处理配置（解决 500/502 错误）
EMBED_BATCH_SIZE = 15  # 每批处理的 chunk 数量（基于字符数分块时可设为10）
EMBED_MAX_RETRIES = 3  # 最大重试次数
EMBED_TIMEOUT = 300  # 单次请求超时（秒）

TEMPERATURE = 0.5

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# RAG检索配置
# 相似度阈值说明：Chroma返回的是余弦距离值，越小越相似
# 余弦距离 = 1 - 余弦相似度，范围0-2，0表示完全相同，2表示完全不同
SIMILARITY_THRESHOLD = 1.0  # 正常匹配阈值（距离值），超过此值进入软拒答
SOFT_REJECTION_THRESHOLD = 2.0  # 软拒答阈值，超过此值完全拒答
RETRIEVE_TOP_K = 7  # 召回段落数（增加以提高匹配概率）
REJECTION_MESSAGE = "未在原著中找到相关内容，无法作答"  # 完全拒答文案
SOFT_REJECTION_MESSAGE = "⚠️ 原著中未找到高度相关的内容，以下回答基于有限信息"  # 软拒答提示


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
