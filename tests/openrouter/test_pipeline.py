"""Requests run through the OpenRouter shims.

Ported from llm-rosetta tests/test_pipeline.py (TestUnsignedBlocksPolicy,
TestReasoningRenameWiring) and tests/test_shims.py
(TestToolGroupsShimDeclarations) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import ConversionPipeline


@pytest.fixture(autouse=True)
def _registered(register):
    register("openrouter")


def test_signature_requiring_shim_withholds_unsigned_reasoning():
    out = ConversionPipeline(
        "chat_completions", "messages", target_shim="openrouter--messages"
    ).convert_request(
        {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "reasoning_content": "think hard",
                    "content": "Hello",
                },
                {"role": "user", "content": "bye"},
            ],
        }
    )
    blocks = [
        block
        for message in out["messages"]
        if message.get("role") == "assistant"
        for block in message.get("content", [])
        if block.get("type") == "thinking"
    ]
    assert blocks == []
    assert out["messages"][1]["content"] == [{"type": "text", "text": "Hello"}]


_SHIM = "openrouter--chat_completions"
_MODEL = "openai/gpt-oss-120b"


def _pipeline():
    pipeline = ConversionPipeline("messages", "chat_completions", target_shim=_SHIM)
    pipeline.convert_request(
        {
            "model": _MODEL,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    return pipeline


def _chunk(delta, finish_reason=None):
    return {
        "id": "chatcmpl-lane",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": _MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def test_non_streaming_response_keeps_the_lane_reasoning():
    out = _pipeline().convert_response(
        {
            "id": "c",
            "object": "chat.completion",
            "created": 1,
            "model": _MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "555",
                        "reasoning": "15*37 = 555",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )
    assert [b["type"] for b in out["content"]] == ["thinking", "text"]
    assert out["content"][0]["thinking"] == "15*37 = 555"


def test_streaming_delta_keeps_the_lane_reasoning():
    processor = _pipeline().create_stream_processor()
    events = []
    for chunk in (
        _chunk({"role": "assistant", "reasoning": "let me think"}),
        _chunk({"content": "555"}),
        _chunk({}, finish_reason="stop"),
    ):
        events.extend(processor.process_chunk(chunk))

    starts = [
        e["content_block"]["type"]
        for e in events
        if e.get("type") == "content_block_start"
    ]
    assert starts == ["thinking", "text"], starts
    thinking = "".join(
        e["delta"]["thinking"]
        for e in events
        if e.get("type") == "content_block_delta"
        and e["delta"]["type"] == "thinking_delta"
    )
    assert thinking == "let me think"


def _namespace_request(**extra):
    return {
        "model": "test-model",
        "tool_choice": "auto",
        "tools": [
            {"type": "function", "name": "plain", "parameters": {}},
            {
                "type": "namespace",
                "name": "tasks",
                "description": "Task management tools.",
                "tools": [
                    {"type": "function", "name": "wait", "parameters": {}},
                    {"type": "function", "name": "edit", "parameters": {}},
                ],
            },
        ],
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            }
        ],
        **extra,
    }


def test_shipping_shim_preserves_containers_in_conversion():
    pipe = ConversionPipeline("open_responses", "openrouter--open_responses")
    tools = pipe.convert_request(_namespace_request())["tools"]
    assert len(tools) == 2
    assert tools[0]["name"] == "plain"
    assert tools[1]["type"] == "namespace"
    assert tools[1]["name"] == "tasks"
    assert tools[1]["description"] == "Task management tools."
    assert [c["name"] for c in tools[1]["tools"]] == ["wait", "edit"]


def test_a_namespace_tool_choice_is_reported_not_silently_dropped():
    pipe = ConversionPipeline("open_responses", "openrouter--open_responses")
    body = pipe.convert_request(
        _namespace_request(
            tool_choice={
                "type": "namespace",
                "name": "tasks",
                "tools": [{"type": "function", "name": "wait"}],
            }
        )
    )
    assert body["tool_choice"] == "auto"
    assert any("namespace tool_choice" in w for w in pipe.warnings)
