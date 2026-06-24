"""analyze_image with mocked vision LLM (no Ollama)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tools import analyze_image


@patch("tools.get_vision_llm")
def test_analyze_image_calls_vision_model(mock_get_llm, minimal_png_path):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="A small square image.")
    mock_get_llm.return_value = mock_llm

    out = analyze_image.invoke({"image_path": str(minimal_png_path)})
    assert out == "A small square image."
    mock_llm.invoke.assert_called_once()
    args = mock_llm.invoke.call_args[0][0]
    assert len(args) == 1
    msg = args[0]
    assert msg.content[0]["type"] == "text"


@patch("tools.get_vision_llm")
def test_analyze_image_missing_file(mock_get_llm, tmp_path):
    missing = tmp_path / "nope.png"
    out = analyze_image.invoke({"image_path": str(missing)})
    assert "No file at" in out
    mock_get_llm.assert_not_called()
