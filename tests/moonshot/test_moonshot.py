"""Moonshot shim: registration and the fields the upstream refuses.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders:
test_moonshot_has_transforms, the shim-set and base-type checks) and
tests/test_transforms.py
(TestBuiltinTransforms::test_moonshot_strips_unsupported) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim
from llm_rosetta.contracts.transform import apply_transforms


@pytest.fixture(autouse=True)
def _registered(register):
    register("moonshot")


def test_registers_the_bare_named_chat_shim():
    shim = get_shim("moonshot")
    assert shim is not None
    assert shim.name == "moonshot"
    assert (shim.model_type, shim.format) == ("llm", "chat_completions")
    assert shim.group is None
    assert shim.connection.api_key_env == "MOONSHOT_API_KEY"
    assert shim.connection.base_url == "https://api.moonshot.cn/v1"


def test_moonshot_has_transforms():
    s = get_shim("moonshot")
    assert len(s.post_ir_transforms) == 1
    assert len(s.pre_ir_transforms) == 0
    body = {
        "logprobs": True,
        "top_logprobs": 5,
        "logit_bias": {},
        "seed": 123,
        "messages": [],
    }
    result = s.post_ir_transforms[0](body)
    for field in ("logprobs", "top_logprobs", "logit_bias", "seed"):
        assert field not in result
    assert "messages" in result


def test_moonshot_strips_unsupported():
    body = {
        "model": "moonshot-v1-8k",
        "logprobs": True,
        "top_logprobs": 3,
        "logit_bias": {},
        "seed": 99,
        "temperature": 0.5,
        "messages": [],
    }
    result = apply_transforms(get_shim("moonshot").post_ir_transforms, body)
    for field in ("logprobs", "top_logprobs", "logit_bias", "seed"):
        assert field not in result
    assert result["model"] == "moonshot-v1-8k"
    assert result["temperature"] == 0.5
