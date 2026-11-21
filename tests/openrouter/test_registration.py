"""OpenRouter shims: registration facts, profile traits and reasoning declarations.

Ported from llm-rosetta tests/test_shim_loader.py, tests/test_shims.py and
tests/test_pipeline.py (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim

_SHIMS = {
    "openrouter--chat_completions": ("llm", "chat_completions"),
    "openrouter--messages": ("llm", "messages"),
    "openrouter--open_responses": ("llm", "open_responses"),
    "openrouter--rerank": ("rerank", "cohere"),
}


@pytest.fixture()
def _registered(register):
    register("openrouter")


def test_third_party_providers_registered(_registered):
    for name in (
        "openrouter--chat_completions",
        "openrouter--messages",
        "openrouter--open_responses",
    ):
        shim = get_shim(name)
        assert shim is not None, f"Built-in shim '{name}' not registered"
        assert shim.name == name


def test_base_types_correct(_registered):
    for name, (model_type, base) in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, f"Shim {name!r} not found"
        assert shim.model_type == model_type, name
        assert shim.format == base, (
            f"{name}: expected base={base!r}, got {shim.format!r}"
        )


def test_default_shim_is_not_free_source(_registered):
    shim = get_shim("openrouter--chat_completions")
    assert shim is not None
    assert shim.free_source is False
    assert shim.connection.keyless is False
    assert shim.display_name is None


def test_the_vendor_declares_no_group(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.group is None and shim.group_label is None, name


def test_openrouter_declares_no_profile_traits(_registered):
    """OpenRouter rejects ``store: true`` outright with HTTP 400."""
    shim = get_shim("openrouter--open_responses")
    assert shim is not None
    assert shim.response_id_prefix == ""
    assert shim.store_default is None
    assert shim.preserve_fields == ()


def test_the_messages_lane_withholds_unsigned_reasoning(_registered):
    """Anthropic rejects a thinking block without a signature (#954).

    Probed live 2026-10-13: openrouter answers 400 for a history carrying an
    unsigned thinking block, so it withholds it.
    """
    shim = get_shim("openrouter--messages")
    assert shim is not None
    assert shim.reasoning is not None
    assert shim.reasoning.unsigned_blocks == "preserve"


def test_the_open_responses_lane_carries_tool_groups(_registered):
    shim = get_shim("openrouter--open_responses")
    assert shim is not None
    assert shim.tools.tool_groups is True


def test_the_chat_lane_renames_reasoning_before_the_ir(_registered):
    shim = get_shim("openrouter--chat_completions")
    assert shim is not None
    assert len(shim.pre_ir_transforms) == 1
