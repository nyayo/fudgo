"""Helpers for envelope-shape assertions."""

from typing import Any


def assert_success(payload: dict[str, Any], expected_keys: set[str]) -> None:
    assert payload["success"] is True
    assert isinstance(payload["data"], dict)
    assert expected_keys.issubset(set(payload["data"].keys()))


def assert_error(payload: dict[str, Any], status: int, code: int | None = None) -> None:
    assert payload["success"] is False
    assert payload["error"]["code"] == (code or status)
    assert isinstance(payload["error"]["message"], str)
    assert isinstance(payload["error"]["details"], dict)