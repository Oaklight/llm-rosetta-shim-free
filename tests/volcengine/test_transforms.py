"""Volcengine chat transforms.

Ported from llm-rosetta tests/test_transforms.py (TestBuiltinTransforms) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim
from llm_rosetta.contracts.transform import apply_transforms


@pytest.fixture()
def _registered(register):
    register("volcengine")


def test_volcengine_has_post_ir_transforms(_registered):
    shim = get_shim("volcengine--chat_completions")
    assert shim is not None
    assert len(shim.post_ir_transforms) > 0


def test_volcengine_strips_logprobs(_registered):
    shim = get_shim("volcengine--chat_completions")
    assert shim is not None
    body = {"model": "test", "logprobs": True, "top_logprobs": 5, "messages": []}
    result = apply_transforms(shim.post_ir_transforms, body)
    assert "logprobs" not in result
    assert "top_logprobs" not in result
    assert result["model"] == "test"
