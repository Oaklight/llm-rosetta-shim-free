"""Rules every ``tier:free`` vendor keeps: keyless, free-source, bilingual."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None  # type: ignore[assignment]

from llm_rosetta.api import get_shim

_PROVIDERS = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "llm_rosetta_shim_contrib"
    / "providers"
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _free_vendors() -> list[str]:
    """The vendors ``vendors.toml`` tags ``tier:free``."""
    text = (_PROVIDERS.parents[2] / "vendors.toml").read_text(encoding="utf-8")
    if tomllib is not None:
        table = tomllib.loads(text)["vendors"]
        return sorted(v for v, e in table.items() if "tier:free" in e["tags"])
    # Python 3.10: the file's tables have a fixed shape.
    found, current = [], None
    for line in text.splitlines():
        m = re.match(r"^\[vendors\.([a-z0-9_]+)\]$", line)
        if m:
            current = m.group(1)
        elif current and line.startswith("tags") and '"tier:free"' in line:
            found.append(current)
    return sorted(found)


FREE = _free_vendors()


def _leaves(vendor: str) -> list[Path]:
    root = _PROVIDERS / vendor
    return sorted(p for p in root.rglob("provider.yaml") if p.parent != root)


def test_the_free_tier_is_the_four_keyless_pools():
    assert FREE == ["kilo_free", "llm7", "opencode_zen_free", "ovhcloud"]


@pytest.mark.parametrize("vendor", FREE)
def test_no_free_leaf_demands_an_api_key(vendor):
    """A free source that demanded a key env var would defeat its own purpose."""
    for leaf in _leaves(vendor):
        connection = _load(leaf).get("connection") or {}
        assert "api_key" not in connection, leaf
        assert "api_key_env" not in connection, leaf


@pytest.mark.parametrize("vendor", FREE)
def test_every_free_shim_is_a_keyless_free_source(register, vendor):
    register(vendor)
    for leaf in _leaves(vendor):
        shim = get_shim(_load(leaf)["name"])
        assert shim is not None, leaf
        assert shim.free_source is True
        assert shim.connection.keyless
        # Keyless means "no key required", not "a key from the environment".
        assert shim.connection.api_key_env is None


def test_the_free_vendors_use_different_base_urls():
    """A copy-paste that left one vendor on another's host would be silent."""
    urls = [_load(leaf)["connection"]["base_url"] for v in FREE for leaf in _leaves(v)]
    assert len(set(urls)) == len(urls)


@pytest.mark.parametrize("vendor", FREE)
def test_every_hint_is_bilingual(vendor):
    """The admin form shows the hint in the operator's language."""
    for leaf in _leaves(vendor):
        hint = _load(leaf)["hint_msg"]
        assert isinstance(hint, dict)
        assert set(hint) >= {"en", "zh"}
        assert all(isinstance(v, str) and v.strip() for v in hint.values())
