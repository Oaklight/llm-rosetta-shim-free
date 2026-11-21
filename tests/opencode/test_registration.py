"""What the three OpenCode shims declare.

Ported from llm-rosetta tests/test_shims.py, tests/test_reasoning_replay.py,
tests/gateway/test_quota.py::TestProbeResolution::test_shims_attach_their_probes
(#1660 S7).  Shim facts are read from the contrib copy, registered alone.
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim, match_model_reasoning

_SHIMS = {
    "opencode--chat_completions": "chat_completions",
    "opencode--messages": "messages",
    "opencode--open_responses": "open_responses",
}


@pytest.fixture()
def _registered(register):
    register("opencode")


def test_registers_the_three_formats(_registered):
    for name, fmt in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, name
        assert shim.name == name
        assert shim.model_type == "llm"
        assert shim.format == fmt


def test_shims_attach_their_probes(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim is not None, name
        assert [p.id for p in shim.quota_probes] == ["opencode_go"], name


def test_the_vendor_manifest_supplies_the_connection_defaults(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim is not None, name
        assert shim.connection.base_url == "https://opencode.ai/zen/go/v1", name
        assert shim.connection.api_key_env == "OPENCODE_API_KEY", name
        assert shim.connection.models_path == "https://opencode.ai/zen/go/v1/models"
        # session_header is parsed from the manifest's connection block.
        assert shim.connection.session_header == "x-opencode-session", name


def test_every_lane_polls_its_quota_in_the_background(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim is not None and shim.quota is not None, name
        assert shim.quota.probe == "opencode_go", name
        assert shim.quota.interval == 300, name


def test_opencode_declares_replay_for_the_deepseek_family(_registered):
    """A vendor shim declares the requirement for a model family (#1143)."""
    shim = get_shim("opencode--chat_completions")
    assert shim is not None
    assert shim.reasoning is not None
    assert shim.reasoning.replay_missing == "as_is"
    assert shim.reasoning.effort_field == "reasoning_effort"
    assert shim.reasoning.effort_range == ("minimal", "high")

    assert shim.model_reasoning is not None
    assert "deepseek*" in shim.model_reasoning
    for model in (
        "deepseek-v4.1-flash",
        "deepseek-v4.1-flash-free",
        "deepseek-v9",
        "deepseek/deepseek-v3",
    ):
        override = match_model_reasoning(shim, model)
        assert override is not None, model
        assert override.replay_missing == "fill_empty", model
        # The override inherits the provider-level fields it does not set.
        assert override.effort_range == ("minimal", "high"), model
    for model in ("claude-sonnet-4", "gpt-5.6", "gemini-3.5-flash"):
        assert match_model_reasoning(shim, model) is None, model


def test_deepseek_and_opencode_declare_the_capability(_registered):
    """Family-scoped, not shim-wide: the same shim fronts Claude/GPT/Gemini."""
    opencode = get_shim("opencode--chat_completions")
    assert opencode is not None and opencode.model_reasoning is not None
    override = match_model_reasoning(opencode, "deepseek-v4.1-flash")
    assert override is not None
    assert override.replay_missing == "fill_empty"
    assert opencode.reasoning is not None
    assert opencode.reasoning.replay_missing == "as_is"
    assert match_model_reasoning(opencode, "claude-sonnet-4") is None


def test_the_messages_lane_preserves_unsigned_blocks(_registered):
    """The Go lane rejects an unsigned thinking block like Anthropic (#954)."""
    shim = get_shim("opencode--messages")
    assert shim is not None
    assert shim.reasoning is not None
    assert shim.reasoning.unsigned_blocks == "preserve"


def test_messages_shim_keeps_the_base_reasoning_cap_fields(_registered):
    """A partial ``reasoning:`` section must not reset the omitted fields (#954).

    The core test compared against the converter's private ``_DEFAULT_ANTHROPIC``;
    here the expected Messages base cap is spelled out.
    """
    shim = get_shim("opencode--messages")
    assert shim is not None
    cap = shim.reasoning
    assert cap is not None
    assert cap.thinking_modes == {
        "auto": "adaptive",
        "enabled": "enabled",
        "disabled": "disabled",
    }
    assert cap.effort_field == "output_config.effort"
    assert cap.effort_range == ("low", "max")
    assert cap.visibility_modes is None
    assert cap.unsigned_blocks == "preserve"


def test_opencode_declares_no_profile_traits(_registered):
    """OpenCode's Responses surface differs per routed model."""
    shim = get_shim("opencode--open_responses")
    assert shim is not None
    assert shim.response_id_prefix == ""
    assert shim.store_default is None
    assert shim.preserve_fields == ()


def test_an_unmeasured_shim_leaves_tool_groups_off(_registered):
    """No shim is turned on by inference: the Responses lane stays flat."""
    shim = get_shim("opencode--open_responses")
    assert shim is not None
    assert shim.tools.tool_groups is False
