"""Shared fixtures."""

from __future__ import annotations

import os

import pytest

# Unit tests do not run Ollama; avoid failing on missing models when importing the app stack.
os.environ.setdefault("SKIP_OLLAMA_CHECK", "1")


# 1x1 transparent PNG (minimal valid file)
MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500001c00000000"
)


@pytest.fixture
def minimal_png_path(tmp_path):
    p = tmp_path / "tiny.png"
    p.write_bytes(MINIMAL_PNG)
    return p
