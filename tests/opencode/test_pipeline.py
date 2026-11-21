"""Conversions toward the OpenCode shims.

Ported from llm-rosetta tests/test_pipeline.py (#1660 S7):
``TestReasoningReplayForVendorLanes`` (opencode cases),
``TestUnsignedBlocksPolicy`` and ``TestMessagesShimReasoningDefaults``
(opencode cases).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import ConversionPipeline


@pytest.fixture(autouse=True)
def _registered(register):
    register("opencode")


class TestReasoningReplayForVendorLanes:
    """OpenCode fronts DeepSeek and inherits its replay rule (#1143)."""

    @staticmethod
    def _source_body(model: str = "deepseek-v4.1-flash"):
        return {
            "model": model,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "read it"}]},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "c1",
                            "name": "read",
                            "input": {"path": "/x"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "c1",
                            "content": "data",
                        }
                    ],
                },
            ],
        }

    @staticmethod
    def _assistant(out):
        return [m for m in out["messages"] if m["role"] == "assistant"][0]

    def test_opencode_deepseek_gets_the_backfill(self):
        out = ConversionPipeline(
            "messages",
            "chat_completions",
            target_shim="opencode--chat_completions",
            # The shape the gateway produces for a model with no declared
            # capabilities; it must not suppress the per-model declaration.
            model_capabilities=["text"],
        ).convert_request(self._source_body())

        assert self._assistant(out)["reasoning_content"] == ""
        assert out["messages"][-1]["role"] == "tool"

    def test_opencode_non_deepseek_model_is_untouched(self):
        out = ConversionPipeline(
            "messages",
            "chat_completions",
            target_shim="opencode--chat_completions",
            model_capabilities=["text", "reasoning"],
        ).convert_request(self._source_body("claude-haiku-4.5"))

        assert "reasoning_content" not in self._assistant(out)

    def test_opencode_family_member_gets_the_backfill(self):
        """A model the shim has never seen is covered by the family pattern."""
        out = ConversionPipeline(
            "messages",
            "chat_completions",
            target_shim="opencode--chat_completions",
        ).convert_request(self._source_body("deepseek-v9"))

        assert self._assistant(out)["reasoning_content"] == ""

    def test_config_override_keeps_the_shim_policy(self):
        """An admin reasoning override must not reset ``replay_missing``."""
        out = ConversionPipeline(
            "messages",
            "chat_completions",
            target_shim="opencode--chat_completions",
            reasoning_config_override={"effort_range": ["low", "high"]},
        ).convert_request(self._source_body())

        assert self._assistant(out)["reasoning_content"] == ""


class TestUnsignedBlocksPolicy:
    """The Go Messages lane withholds unsigned reasoning (#954)."""

    @staticmethod
    def _source_body():
        """A Chat history whose assistant turn carries reasoning, no signature."""
        return {
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

    @staticmethod
    def _thinking_blocks(out):
        return [
            block
            for message in out["messages"]
            if message.get("role") == "assistant"
            for block in message.get("content", [])
            if block.get("type") == "thinking"
        ]

    def test_signature_requiring_shim_withholds_unsigned_reasoning(self):
        out = ConversionPipeline(
            "chat_completions", "messages", target_shim="opencode--messages"
        ).convert_request(self._source_body())

        assert self._thinking_blocks(out) == []
        assert out["messages"][1]["content"] == [{"type": "text", "text": "Hello"}]

    def test_bare_conversion_sends_it_unsigned(self):
        """Without a shim the default policy is ``as_is``."""
        out = ConversionPipeline("chat_completions", "messages").convert_request(
            self._source_body()
        )

        blocks = self._thinking_blocks(out)
        assert len(blocks) == 1
        assert "signature" not in blocks[0]


class TestMessagesShimReasoningDefaults:
    """Adding a shim ``reasoning:`` section must not reset the cap (#954)."""

    def test_effort_still_goes_out_as_output_config(self):
        out = ConversionPipeline(
            "chat_completions", "messages", target_shim="opencode--messages"
        ).convert_request(
            {
                "model": "m",
                "reasoning_effort": "high",
                "messages": [{"role": "user", "content": "hi"}],
            }
        )

        assert out["thinking"] == {"type": "adaptive"}
        assert out["output_config"] == {"effort": "high"}
        assert "reasoning_effort" not in out
