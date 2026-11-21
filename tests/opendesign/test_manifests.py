"""The bundled YAML declares the canonical names and bilingual hints."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_PROVIDERS = _ROOT / "src" / "llm_rosetta_shim_contrib" / "providers"
_VENDOR = _PROVIDERS / "opendesign" / "provider.yaml"
_LEAVES = {
    "chat_completions": _PROVIDERS
    / "opendesign"
    / "llm"
    / "chat_completions"
    / "provider.yaml",
    "open_responses": _PROVIDERS
    / "opendesign"
    / "llm"
    / "open_responses"
    / "provider.yaml",
    "messages": _PROVIDERS / "opendesign" / "llm" / "messages" / "provider.yaml",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_vendor_manifest_declares_only_shared_defaults():
    """The mark and the connection are the vendor's; a lane keeps its own facts."""
    cfg = _load(_VENDOR)
    assert set(cfg) == {"logo", "connection"}
    assert cfg["logo"] == (
        "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-opendesign@main/"
        "assets/opendesign.svg"
    )
    connection = cfg["connection"]
    assert connection["base_url"] == "https://amr-link.open-design.ai/v1"
    # auth.py owns the credential slot; an environment default beside it
    # would advertise a source the gateway refuses.
    assert "api_key_env" not in connection
    assert connection["models_path"] == "https://amr-link.open-design.ai/v1/models"
    assert connection["manage_usage_url"] == "https://open-design.ai/cloud/usage"
    # The allowance is the account's, but it sits on the leaves for now: a
    # core older than the manifest's `quota:` key refuses this file outright.
    assert "quota" not in cfg


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_no_leaf_restates_the_shared_identity(fmt: str, path: Path):
    """A second lane inherits the mark; restating it is how the copies drift."""
    cfg = _load(path)
    assert {"logo", "group", "group_label"}.isdisjoint(cfg)


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_each_leaf_names_its_format(fmt: str, path: Path):
    cfg = _load(path)
    assert cfg["name"] == f"opendesign--{fmt}"
    assert cfg["model_type"] == "llm"
    assert cfg["format"] == fmt


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_each_hint_is_bilingual(fmt: str, path: Path):
    hint = _load(path)["hint_msg"]
    assert isinstance(hint, dict)
    assert set(hint) == {"en", "zh"}
    assert all(isinstance(value, str) and value.strip() for value in hint.values())


@pytest.mark.parametrize("fmt,path", sorted(_LEAVES.items()))
def test_no_leaf_declares_a_credential(fmt: str, path: Path):
    """The vendor manifest is the only credential home."""
    cfg = _load(path)
    credential_keys = {
        "api_key",
        "api_key_env",
        "control_api_key",
        "control_api_key_env",
        "token_command",
        "token_command_env",
    }
    assert credential_keys.isdisjoint(cfg)
    assert credential_keys.isdisjoint(cfg.get("connection") or {})
    # The allowance is declared per leaf until the dependency floor moves to a
    # core that reads it from the manifest; every lane reads the same plane.
    assert cfg["quota"] == {
        "probe": "opendesign",
        "url": "https://amr-api.open-design.ai",
    }
