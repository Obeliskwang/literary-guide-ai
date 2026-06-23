"""Tests for multimodal HumanMessage construction."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from tools import _human_message_with_image


def test_human_message_with_image_structure(minimal_png_path):
    msg = _human_message_with_image("Describe this.", str(minimal_png_path))
    assert isinstance(msg, HumanMessage)
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert msg.content[0]["type"] == "text"
    assert msg.content[0]["text"] == "Describe this."
    assert msg.content[1]["type"] == "image_url"
    url = msg.content[1]["image_url"]
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 40
