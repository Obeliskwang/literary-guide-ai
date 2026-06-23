"""Tests for RAG search_documents tool factory."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.documents import Document

from tools import build_search_documents_tool


def test_search_documents_returns_joined_chunks():
    store = MagicMock()
    store.similarity_search.return_value = [
        Document(page_content="alpha"),
        Document(page_content="beta"),
    ]
    tool = build_search_documents_tool(store)
    out = tool.invoke({"query": "topic"})
    assert out == "alpha\nbeta"
    store.similarity_search.assert_called_once_with("topic", k=3)
