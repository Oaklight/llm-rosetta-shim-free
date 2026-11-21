"""Z.ai shims: registration facts, the vendor title and the GLM request ranges.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders,
TestDeclaredGrouping) and tests/test_shims.py
(TestRequestConstraintDeclarations, TestZhipuRequestRanges) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import ConversionPipeline, get_shim

_SHIMS = {
    "zai--chat_completions": ("llm", "chat_completions"),
    "zai--messages": ("llm", "messages"),
    "zai--embedding": ("embeddings", "openai"),
    "zai--rerank": ("rerank", "cohere"),
}


@pytest.fixture()
def _registered(register):
    register("zai")


def test_registers_every_lane(_registered):
    for name, (model_type, base) in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, f"Shim {name!r} not found"
        assert shim.name == name
        assert shim.model_type == model_type, name
        assert shim.format == base, (
            f"{name}: expected base={base!r}, got {shim.format!r}"
        )


def test_the_vendor_title_is_the_product_name(_registered):
    """Z.ai is Zhipu's international platform; the title is a product name,
    not the mangled directory key, and no lane declares a ``group``."""
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.group_label == "Z.ai", name
        assert shim.group is None, name


def test_only_the_chat_lane_declares_constraints(_registered):
    """Z.ai carries the GLM temperature range on the chat lane only.

    No other lane has been measured, and an unmeasured declaration is worse
    than none.
    """
    declared = {name for name in _SHIMS if get_shim(name) and get_shim(name).request}
    assert declared == {"zai--chat_completions"}, sorted(declared)


def _convert(**generation: object):
    pipe = ConversionPipeline("chat_completions", "zai--chat_completions")
    body = pipe.convert_request(
        {"model": "m", "messages": [{"role": "user", "content": "hi"}], **generation}
    )
    return body, pipe


def _range_warnings(pipe):
    return [w for w in pipe.warnings if "outside the range" in str(w)]


def test_temperature_above_one_is_clamped_and_reported(_registered):
    body, pipe = _convert(temperature=1.8)
    assert body["temperature"] == 1.0
    assert [w.subject for w in _range_warnings(pipe)] == ["generation.temperature"]


def test_values_inside_the_range_are_untouched(_registered):
    body, pipe = _convert(temperature=0.7, top_p=0.9)
    assert (body["temperature"], body["top_p"]) == (0.7, 0.9)
    assert not _range_warnings(pipe)


def test_top_p_is_not_clamped(_registered):
    """Unlike the domestic lane, nothing is declared for ``top_p``."""
    body, pipe = _convert(top_p=1.5)
    assert body["top_p"] == 1.5
    assert not _range_warnings(pipe)
