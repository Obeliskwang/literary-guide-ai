# -*- coding: utf-8 -*-
"""
二阶段重排序模块（Reranker）

使用 CrossEncoder 模型对向量检索召回的片段进行精排，
提升检索精准度，抑制噪声片段。

默认不启用（USE_RERANKER = False），答辩稳定运行后可开启。
"""

import logging
from config import (
    RERANKER_MODEL_NAME,
    RERANKER_TOP_N,
    RERANKER_SCORE_THRESHOLD,
)

logger = logging.getLogger(__name__)

_reranker_model = None
_reranker_loaded = False
_reranker_load_failed = False


def _load_reranker():
    """
    懒加载 CrossEncoder 重排模型。

    首次调用时加载，之后复用单例。
    如果 sentence-transformers 未安装或模型下载失败，返回 None，
    调用方应优雅降级（跳过重排，直接使用原检索结果）。
    """
    global _reranker_model, _reranker_loaded, _reranker_load_failed

    if _reranker_loaded:
        return _reranker_model

    if _reranker_load_failed:
        return None

    try:
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker model: %s", RERANKER_MODEL_NAME)
        _reranker_model = CrossEncoder(RERANKER_MODEL_NAME)
        _reranker_loaded = True
        logger.info("Reranker model loaded successfully")
        return _reranker_model
    except ImportError:
        logger.warning(
            "sentence-transformers not installed, reranker disabled. "
            "Install with: pip install sentence-transformers"
        )
        _reranker_load_failed = True
        return None
    except Exception as e:
        logger.error("Failed to load reranker model: %s", e)
        _reranker_load_failed = True
        return None


def rerank_chunks(query, results_with_score, top_n=None, score_threshold=None):
    """
    对向量检索结果进行 CrossEncoder 重排序。

    参数:
        query: str - 用户问题
        results_with_score: list - 向量检索结果，每项格式为
            {"document": Document, "distance": float}
        top_n: int - 返回前 N 个结果，默认使用配置值
        score_threshold: float - 重排分数阈值，低于此值的片段被过滤，
            默认使用配置值

    返回:
        list - 重排后的结果，格式与输入相同，按重排分数从高到低排序，
            每项额外增加 "rerank_score" 字段
        如果重排器不可用，返回原结果（不增加 rerank_score）
    """
    if top_n is None:
        top_n = RERANKER_TOP_N
    if score_threshold is None:
        score_threshold = RERANKER_SCORE_THRESHOLD

    if not results_with_score:
        return []

    model = _load_reranker()
    if model is None:
        logger.info("Reranker not available, returning original results")
        return results_with_score

    try:
        pairs = []
        for item in results_with_score:
            text = item["document"].page_content.strip()
            pairs.append([query, text])

        logger.info("Reranking %d chunks with CrossEncoder", len(pairs))
        scores = model.predict(pairs)

        scored_results = []
        for item, score in zip(results_with_score, scores):
            item_copy = dict(item)
            item_copy["rerank_score"] = float(score)
            scored_results.append(item_copy)

        scored_results.sort(key=lambda x: x["rerank_score"], reverse=True)

        filtered = [
            r for r in scored_results if r["rerank_score"] >= score_threshold
        ]

        logger.info(
            "Rerank done: %d -> %d chunks (threshold=%.3f)",
            len(scored_results),
            len(filtered),
            score_threshold,
        )

        if filtered:
            top_score = filtered[0]["rerank_score"]
            logger.info("Top rerank score: %.4f", top_score)

        return filtered[:top_n]

    except Exception as e:
        logger.error("Reranking failed, falling back to original results: %s", e)
        return results_with_score
