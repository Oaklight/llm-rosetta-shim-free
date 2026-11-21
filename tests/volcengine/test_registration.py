"""Volcengine (ARK) shims: registration facts and Responses profile traits.

Ported from llm-rosetta tests/test_shim_loader.py, tests/test_shims.py and
tests/test_intrinsic_tool_declaration.py (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim

_SHIMS = {
    "volcengine--chat_completions": ("llm", "chat_completions"),
    "volcengine--open_responses": ("llm", "open_responses"),
    "volcengine--embedding": ("embeddings", "openai"),
}


@pytest.fixture()
def _registered(register):
    register("volcengine")


def test_third_party_providers_registered(_registered):
    for name in ("volcengine--chat_completions", "volcengine--open_responses"):
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


def test_the_vendor_declares_no_group(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.group is None and shim.group_label is None, name


def test_volcengine_has_transforms(_registered):
    """Volcengine shim should have strip_fields transforms loaded."""
    v = get_shim("volcengine--chat_completions")
    assert v is not None
    assert len(v.post_ir_transforms) == 1
    assert len(v.pre_ir_transforms) == 0
    body = {"logprobs": True, "top_logprobs": 5, "messages": []}
    result = v.post_ir_transforms[0](body)
    assert "logprobs" not in result
    assert "messages" in result


def test_volcengine_keeps_store_and_gains_prefix(_registered):
    """ARK is the one non-OpenAI shim where ``store_default: true`` holds.

    ARK defaults to server-side storage and honors ``store: false`` when sent.
    """
    shim = get_shim("volcengine--open_responses")
    assert shim is not None
    assert shim.response_id_prefix == "resp_"
    assert shim.store_default is True
    assert shim.preserve_fields == ()


def test_volcengine_declares_no_intrinsic_tools(_registered):
    """The ARK account gate, not the wire shape, decides this one.

    Measured live 2026-10-23: the declaration is accepted, but a request that
    invokes the tool answers 404 ``ToolNotOpen`` until web search is activated
    on the account.
    """
    shim = get_shim("volcengine--open_responses")
    assert shim is not None
    assert set(shim.tools.intrinsic_tools) == set()


def test_the_open_responses_lane_carries_tool_groups(_registered):
    shim = get_shim("volcengine--open_responses")
    assert shim is not None
    assert shim.tools.tool_groups is True
