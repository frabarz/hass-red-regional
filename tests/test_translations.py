"""Unit tests for Red Regional translation completeness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TRANSLATIONS = Path("custom_components/red_regional/translations")


def _flatten(obj: Any, prefix: str = "") -> set[str]:
    """Flatten nested translation dicts into dotted key paths."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for name, value in obj.items():
            keys |= _flatten(value, f"{prefix}{name}.")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            keys |= _flatten(value, f"{prefix}{index}.")
    else:
        keys.add(prefix.rstrip("."))
    return keys


def _load(language: str) -> dict[str, Any]:
    return json.loads((TRANSLATIONS / f"{language}.json").read_text())


def test_en_es_key_parity() -> None:
    """English and Spanish files expose identical key trees."""
    assert _flatten(_load("en")) == _flatten(_load("es"))


def test_no_core_placeholders() -> None:
    """Custom integrations must ship literal text, not build-time keys."""
    for language in ("en", "es"):
        text = (TRANSLATIONS / f"{language}.json").read_text()
        assert "[%key" not in text
        assert json.loads(text)
