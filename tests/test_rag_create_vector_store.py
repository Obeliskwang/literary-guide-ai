"""create_vector_store with Chroma and embeddings mocked (no Ollama)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


@patch("rag.Chroma")
@patch("rag.get_embeddings")
def test_create_vector_store_calls_chroma(mock_get_embeddings, mock_chroma):
    mock_get_embeddings.return_value = MagicMock(name="emb")
    mock_chroma.from_documents.return_value = MagicMock(name="db")

    from rag import create_vector_store

    text = "word " * 200  # enough text for splitting
    db = create_vector_store(text)

    assert db is not None
    mock_get_embeddings.assert_called_once()
    mock_chroma.from_documents.assert_called_once()
    call_kw = mock_chroma.from_documents.call_args
    docs = call_kw[0][0]
    assert len(docs) >= 1
