"""SiliconFlow shims: registration facts.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders,
TestDeclaredGrouping) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_shim

_SHIMS = {
    "siliconflow--chat_completions": ("llm", "chat_completions"),
    "siliconflow--embedding": ("embeddings", "openai"),
    "siliconflow--rerank": ("rerank", "cohere"),
}


@pytest.fixture()
def _registered(register):
    register("siliconflow")


def test_registers_every_lane(_registered):
    for name, (model_type, base) in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, f"Shim {name!r} not found"
        assert shim.name == name
        assert shim.model_type == model_type, name
        assert shim.format == base, (
            f"{name}: expected base={base!r}, got {shim.format!r}"
        )


def test_the_vendor_declares_no_group(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.group is None and shim.group_label is None, name
