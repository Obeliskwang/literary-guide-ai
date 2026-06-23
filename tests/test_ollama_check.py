"""Tests for Ollama model presence checks."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ollama_check import OllamaModelsError, ensure_ollama_models, _model_is_present


def test_model_is_present_exact_and_tag():
    assert _model_is_present("llama3.2", ["llama3.2:latest", "other:latest"])
    assert _model_is_present("llama3.2", ["llama3.2"])
    assert not _model_is_present("llama3.2", ["llama3:latest"])


@patch("ollama_check._fetch_installed_model_names")
def test_ensure_passes_when_all_models_installed(mock_fetch, monkeypatch):
    monkeypatch.delenv("SKIP_OLLAMA_CHECK", raising=False)
    mock_fetch.return_value = [
        "llama3.2:latest",
        "mxbai-embed-large:latest",
        "llava:latest",
    ]
    ensure_ollama_models()  # no raise


@patch("ollama_check._fetch_installed_model_names")
def test_ensure_raises_when_model_missing(mock_fetch, monkeypatch):
    monkeypatch.delenv("SKIP_OLLAMA_CHECK", raising=False)
    mock_fetch.return_value = ["llama3.2:latest"]
    with pytest.raises(OllamaModelsError, match="ollama pull"):
        ensure_ollama_models()


@patch("ollama_check._fetch_installed_model_names")
def test_skip_env_disables_check(mock_fetch, monkeypatch):
    monkeypatch.setenv("SKIP_OLLAMA_CHECK", "1")
    mock_fetch.return_value = []
    ensure_ollama_models()
    mock_fetch.assert_not_called()
