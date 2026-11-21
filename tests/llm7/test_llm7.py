"""LLM7.io: anonymous free gateway; reasoning rename and the turbo-tier filter."""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_model_list_transform, get_shim

SHIM = "llm7--chat_completions"


@pytest.fixture()
def _registered(register):
    register("llm7")


def test_registers_with_its_base_url(_registered):
    shim = get_shim(SHIM)
    assert shim is not None
    assert shim.model_type == "llm"
    assert shim.format == "chat_completions"
    assert shim.connection.base_url == "https://api.llm7.io/v1"
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


def test_offers_only_free_chat_models(_registered):
    transform = get_model_list_transform(SHIM)
    assert transform is not None
    entries = [
        {"id": "chat-turbo-a", "model_type": "chat", "tier": "turbo"},
        {"id": "chat-turbo-b", "model_type": "chat", "tier": "turbo"},
        {"id": "chat-pro", "model_type": "chat", "tier": "pro"},
        {"id": "image-turbo", "model_type": "image", "tier": "turbo"},
        {"id": "decision", "model_type": "systemone", "tier": "pro"},
        {"model_type": "chat", "tier": "turbo"},  # no id
    ]
    ids, upstream = transform(entries)
    assert ids == ["chat-turbo-a", "chat-turbo-b"]
    assert upstream == {}
