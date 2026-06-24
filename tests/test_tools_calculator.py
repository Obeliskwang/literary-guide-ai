"""Tests for the calculator tool."""

from __future__ import annotations

from tools import calculator


def test_calculator_simple_math():
    out = calculator.invoke({"expression": "2 + 3"})
    assert out == "5"


def test_calculator_multiplication():
    out = calculator.invoke({"expression": "7 * 6"})
    assert out == "42"


def test_calculator_invalid_expression():
    out = calculator.invoke({"expression": "1/0"})
    assert "division" in out.lower() or "zero" in out.lower()
