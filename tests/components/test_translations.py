"""Cohérence entre services.yaml et les traductions (ce que contrôle aussi hassfest)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "cospend"
SERVICES = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))


def load(lang: str) -> dict:
    return json.loads((COMPONENT / "translations" / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_every_service_and_field_is_translated(lang: str) -> None:
    translated = load(lang)["services"]
    assert set(translated) == set(SERVICES)
    for name, definition in SERVICES.items():
        fields = definition["fields"]
        assert set(translated[name]["fields"]) == set(fields), name
        assert translated[name]["name"] and translated[name]["description"]
        for field, text in translated[name]["fields"].items():
            assert text["name"] and text["description"], (name, field)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_selector_translations_cover_the_select_options(lang: str) -> None:
    selectors = load(lang)["selector"]
    for definition in SERVICES.values():
        for field in definition["fields"].values():
            select = field["selector"].get("select")
            if select:
                assert set(selectors[select["translation_key"]]["options"]) == set(
                    select["options"]
                )


def test_english_and_french_have_the_same_keys() -> None:
    def keys(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from keys(value, f"{prefix}.{key}")
        else:
            yield prefix

    assert set(keys(load("en"))) == set(keys(load("fr")))


def test_error_messages_use_known_translation_keys() -> None:
    import re

    source = (COMPONENT / "services.py").read_text(encoding="utf-8")
    used = set(re.findall(r'(?:_error\(|translation_key=)"([a-z_]+)"', source))
    assert used
    assert used <= set(load("en")["exceptions"])


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_braces_are_only_valid_placeholders(lang: str) -> None:
    """hassfest refuse toute accolade qui n'est pas un ``{identifiant}``."""
    import re

    def strings(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, str):
            yield node

    for text in strings(load(lang)):
        for inner in re.findall(r"\{([^}]*)\}", text):
            assert re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", inner), text
        assert text.count("{") == text.count("}"), text
