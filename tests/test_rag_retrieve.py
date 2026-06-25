"""Tests for rag.retrieve."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.documents import Document

from config import RETRIEVE_TOP_K
from rag import retrieve


def test_retrieve_returns_ranked_results():
    store = MagicMock()
    docs = [(Document(page_content="x"), 0.4), (Document(page_content="y"), 0.8)]
    store.similarity_search_with_score.return_value = docs

    out = retrieve(store, "query text")

    assert out["reject"] is False
    assert out["soft_reject"] is False
    assert out["min_distance"] == 0.4
    assert len(out["results"]) == 2
    store.similarity_search_with_score.assert_called_once_with("query text", k=RETRIEVE_TOP_K)
