"""Requests run through the Volcengine shims.

Ported from llm-rosetta tests/test_shims.py (TestResponsesProfileTraitsBehavior,
TestShimConverterIntegration, TestToolGroupsShimDeclarations) and
tests/test_intrinsic_tool_declaration.py (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import (
    ConversionPipeline,
    get_converter_for_provider,
    get_converter_class,
)


@pytest.fixture(autouse=True)
def _registered(register):
    register("volcengine")


_REQUEST = {"model": "gpt-4o-mini", "input": "hi"}
_UPSTREAM = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4o-mini",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def test_volcengine_response_forces_store():
    """ARK defaults to server-side storage, so it keeps the default too."""
    pipeline = ConversionPipeline("volcengine--open_responses", "chat_completions")
    pipeline.convert_request(dict(_REQUEST))
    result = pipeline.convert_response(dict(_UPSTREAM))
    assert result["store"] is True


def test_volcengine_resolves_to_openai_chat_converter():
    converter = get_converter_for_provider("volcengine--chat_completions")
    assert isinstance(converter, get_converter_class("llm", "chat_completions"))


def test_ark_lane_drops_and_reports_web_search():
    """A request against the undeclared lane loses the tool loudly.

    Source and target must differ: a same-format conversion keeps its own
    native declarations untouched, which would hide the gate.
    """
    pipe = ConversionPipeline(
        "messages", "open_responses", target_shim="volcengine--open_responses"
    )
    body = pipe.convert_request(
        {
            "model": "m",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        }
    )
    assert not any("web_search" in str(t) for t in body.get("tools") or [])
    assert any("web_search" in warning for warning in pipe.warnings)


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
    pipe = ConversionPipeline("open_responses", "volcengine--open_responses")
    tools = pipe.convert_request(_namespace_request())["tools"]
    assert len(tools) == 2
    assert tools[0]["name"] == "plain"
    assert tools[1]["type"] == "namespace"
    assert tools[1]["name"] == "tasks"
    assert tools[1]["description"] == "Task management tools."
    assert [c["name"] for c in tools[1]["tools"]] == ["wait", "edit"]


def test_a_namespace_tool_choice_is_reported_not_silently_dropped():
    """The IR ``ToolChoice`` has no group slot, so the read leg falls back to
    ``auto`` and reports it rather than dropping the force without a word."""
    pipe = ConversionPipeline("open_responses", "volcengine--open_responses")
    request = _namespace_request(
        tool_choice={
            "type": "namespace",
            "name": "tasks",
            "tools": [{"type": "function", "name": "wait"}],
        }
    )
    body = pipe.convert_request(request)
    assert body["tool_choice"] == "auto"
    assert any("namespace tool_choice" in w for w in pipe.warnings)
