"""OVHcloud AI Endpoints: anonymous free tier; reasoning rename, no model filter."""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_model_list_transform, get_shim

SHIM = "ovhcloud--chat_completions"


@pytest.fixture()
def _registered(register):
    register("ovhcloud")


def test_registers_with_its_base_url(_registered):
    shim = get_shim(SHIM)
    assert shim is not None
    assert shim.model_type == "llm"
    assert shim.format == "chat_completions"
    assert (
        shim.connection.base_url == "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
    )
    # The vendor manifest is a marker: every connection fact is on the leaf.
    assert shim.manifest is not None
    assert shim.manifest.connection == {}


def _apply(shim_name: str, body: dict) -> dict:
    shim = get_shim(shim_name)
    assert shim is not None
    for transform in shim.pre_ir_transforms:
        body = transform(body)
    return body


def test_reasoning_is_renamed_on_the_message(_registered):
    body = {
        "choices": [
            {"message": {"role": "assistant", "reasoning": "thinking", "content": "hi"}}
        ]
    }
    message = _apply(SHIM, body)["choices"][0]["message"]
    assert message["reasoning_content"] == "thinking"
    assert "reasoning" not in message


def test_reasoning_is_renamed_on_the_stream_delta(_registered):
    """The streaming path is the one that loses the text silently."""
    body = _apply(SHIM, {"choices": [{"delta": {"reasoning": "part"}}]})
    assert body["choices"][0]["delta"]["reasoning_content"] == "part"


def test_a_response_without_reasoning_is_untouched(_registered):
    body = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    before = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    assert _apply(SHIM, body) == before


def test_ships_no_model_list_hook(_registered):
    """Without a hook the admin sorts the upstream list itself."""
    assert get_model_list_transform(SHIM) is None
