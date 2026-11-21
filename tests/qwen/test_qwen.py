"""Qwen (DashScope) shim: registration and the fields the upstream refuses.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders:
test_qwen_has_transforms, the shim-set and base-type checks) and
tests/test_transforms.py (TestBuiltinTransforms::test_qwen_strips_unsupported)
(#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim
from llm_rosetta.contracts.transform import apply_transforms


@pytest.fixture(autouse=True)
def _registered(register):
    register("qwen")


def test_registers_the_bare_named_chat_shim():
    shim = get_shim("qwen")
    assert shim is not None
    assert shim.name == "qwen"
    assert (shim.model_type, shim.format) == ("llm", "chat_completions")
    assert shim.group is None
    assert shim.connection.api_key_env == "DASHSCOPE_API_KEY"
    assert (
        shim.connection.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_qwen_has_transforms():
    s = get_shim("qwen")
    assert len(s.post_ir_transforms) == 1
    assert len(s.pre_ir_transforms) == 0
    body = {"frequency_penalty": 0.5, "logit_bias": {}, "messages": []}
    result = s.post_ir_transforms[0](body)
    assert "frequency_penalty" not in result
    assert "logit_bias" not in result
    assert "messages" in result


def test_qwen_strips_unsupported():
    body = {
        "model": "qwen-max",
        "frequency_penalty": 0.5,
        "logit_bias": {"50256": -100},
        "temperature": 0.7,
        "messages": [],
    }
    result = apply_transforms(get_shim("qwen").post_ir_transforms, body)
    assert "frequency_penalty" not in result
    assert "logit_bias" not in result
    assert result["model"] == "qwen-max"
    assert result["temperature"] == 0.7
