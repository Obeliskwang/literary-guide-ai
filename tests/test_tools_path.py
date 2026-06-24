"""Tests for path resolution used by analyze_image."""

from __future__ import annotations

from tools import _resolve_local_path


def test_resolve_local_path_expands_user_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    f = tmp_path / "doc.txt"
    f.write_text("x", encoding="utf-8")
    out = _resolve_local_path("~/doc.txt")
    assert out == str(f.resolve())


def test_resolve_local_path_expands_dollar_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    f = tmp_path / "pic.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n")
    out = _resolve_local_path("$HOME/pic.png")
    assert out == str(f.resolve())
