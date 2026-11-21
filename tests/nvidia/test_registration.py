"""NVIDIA shim: registration facts.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders,
TestDeclaredGrouping) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim


@pytest.fixture()
def _registered(register):
    register("nvidia")


def test_registers_the_chat_lane(_registered):
    shim = get_shim("nvidia--chat_completions")
    assert shim is not None
    assert shim.name == "nvidia--chat_completions"
    assert shim.model_type == "llm"
    assert shim.format == "chat_completions"


def test_the_vendor_declares_no_group(_registered):
    shim = get_shim("nvidia--chat_completions")
    assert shim.group is None and shim.group_label is None
    assert shim.display_name is None
