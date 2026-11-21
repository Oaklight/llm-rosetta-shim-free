"""xAI shim: registration and the fields the upstream refuses.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders:
test_xai_has_transforms, the shim-set and base-type checks),
tests/test_transforms.py (TestBuiltinTransforms::test_xai_strips_logit_bias)
and tests/test_pipeline.py
(test_shim_without_the_capability_leaves_field_absent) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import ConversionPipeline, get_shim
from llm_rosetta.contracts.transform import apply_transforms


@pytest.fixture(autouse=True)
def _registered(register):
    register("xai")


def test_registers_the_bare_named_chat_shim():
    shim = get_shim("xai")
    assert shim is not None
    assert shim.name == "xai"
    assert (shim.model_type, shim.format) == ("llm", "chat_completions")
    assert shim.group is None
    assert shim.connection.api_key_env == "XAI_API_KEY"
    assert shim.connection.base_url == "https://api.x.ai/v1"


def test_xai_has_transforms():
    s = get_shim("xai")
    assert len(s.post_ir_transforms) == 1
    assert len(s.pre_ir_transforms) == 0
    result = s.post_ir_transforms[0]({"logit_bias": {"50256": -100}, "messages": []})
    assert "logit_bias" not in result
    assert "messages" in result


def test_xai_strips_logit_bias():
    body = {
        "model": "grok-3",
        "logit_bias": {"50256": -100},
        "temperature": 1.0,
        "messages": [],
    }
    result = apply_transforms(get_shim("xai").post_ir_transforms, body)
    assert "logit_bias" not in result
    assert result["model"] == "grok-3"
    assert result["temperature"] == 1.0


def test_shim_without_the_replay_capability_leaves_reasoning_content_absent():
    """The reasoning_content backfill is gated on a declared capability."""
    source = {
        "model": "m",
        "max_tokens": 256,
        "messages": [
            {"role": "user", "content": "read it"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "read", "input": {}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "x"}
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t2", "name": "read", "input": {}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t2", "content": "y"}
                ],
            },
        ],
        "tools": [{"name": "read", "input_schema": {"type": "object"}}],
    }
    out = ConversionPipeline(
        "messages", "chat_completions", target_shim="xai"
    ).convert_request(source)
    callers = [m for m in out["messages"] if m.get("tool_calls")]
    assert callers
    assert all("reasoning_content" not in m for m in callers)
