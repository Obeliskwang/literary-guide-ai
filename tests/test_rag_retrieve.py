"""Tests for rag.retrieve."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.documents import Document

from rag import retrieve


def test_retrieve_delegates_to_vector_store():
    store = MagicMock()
    docs = [Document(page_content="x")]
    store.similarity_search.return_value = docs
    out = retrieve(store, "query text")
    assert out == docs
    store.similarity_search.assert_called_once_with("query text", k=3)
