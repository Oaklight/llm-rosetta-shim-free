"""Zhipu shims: registration, stripped fields and the GLM request ranges.

Ported from llm-rosetta tests/test_shim_loader.py (TestLoadProviders:
test_zhipu_has_transforms, the shim-set and base-type checks),
tests/test_transforms.py (TestBuiltinTransforms::test_zhipu_strips_unsupported)
and tests/test_shims.py (TestRequestConstraintDeclarations,
TestZhipuRequestRanges) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import ConversionPipeline, get_shim
from llm_rosetta.contracts.transform import apply_transforms

_SHIMS = {
    "zhipu": ("llm", "chat_completions"),
    "zhipu--embedding": ("embeddings", "openai"),
    "zhipu--rerank": ("rerank", "cohere"),
}

_STRIPPED = (
    "n",
    "presence_penalty",
    "frequency_penalty",
    "logprobs",
    "top_logprobs",
    "logit_bias",
    "seed",
)


@pytest.fixture(autouse=True)
def _registered(register):
    register("zhipu")


def test_registers_every_lane():
    for name, (model_type, base) in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, name
        assert shim.name == name
        assert (shim.model_type, shim.format) == (model_type, base), name
        assert shim.group is None, name
        assert shim.connection.api_key_env == "ZHIPU_API_KEY", name


def test_zhipu_has_transforms():
    s = get_shim("zhipu")
    assert len(s.post_ir_transforms) == 1
    assert len(s.pre_ir_transforms) == 0
    body = {
        "n": 2,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.5,
        "logprobs": True,
        "top_logprobs": 5,
        "logit_bias": {},
        "seed": 42,
        "messages": [],
    }
    result = s.post_ir_transforms[0](body)
    for field in _STRIPPED:
        assert field not in result
    assert "messages" in result


def test_zhipu_strips_unsupported():
    body = {
        "model": "glm-4",
        "n": 2,
        "presence_penalty": 0.5,
        "frequency_penalty": 0.5,
        "logprobs": True,
        "top_logprobs": 5,
        "logit_bias": {},
        "seed": 99,
        "temperature": 0.8,
        "messages": [],
    }
    result = apply_transforms(get_shim("zhipu").post_ir_transforms, body)
    for field in _STRIPPED:
        assert field not in result
    assert result["model"] == "glm-4"
    assert result["temperature"] == 0.8


def test_only_the_chat_lane_declares_constraints():
    declared = {name for name in _SHIMS if get_shim(name).request}
    assert declared == {"zhipu"}


def _convert(**generation: object):
    pipe = ConversionPipeline("chat_completions", "zhipu")
    body = pipe.convert_request(
        {"model": "m", "messages": [{"role": "user", "content": "hi"}], **generation}
    )
    return body, pipe


def _range_subjects(pipe) -> list[str]:
    return [w.subject for w in pipe.warnings if "outside the range" in str(w)]


def test_temperature_above_one_is_clamped_and_reported():
    body, pipe = _convert(temperature=1.8)
    assert body["temperature"] == 1.0
    assert _range_subjects(pipe) == ["generation.temperature"]


def test_top_p_below_the_minimum_is_clamped_and_reported():
    body, pipe = _convert(top_p=0.001)
    assert body["top_p"] == 0.01
    assert _range_subjects(pipe) == ["generation.top_p"]


def test_top_p_above_one_is_clamped_and_reported():
    body, pipe = _convert(top_p=1.5)
    assert body["top_p"] == 1.0
    assert _range_subjects(pipe) == ["generation.top_p"]


def test_values_inside_the_ranges_are_untouched():
    body, pipe = _convert(temperature=0.7, top_p=0.9)
    assert (body["temperature"], body["top_p"]) == (0.7, 0.9)
    assert not _range_subjects(pipe)
