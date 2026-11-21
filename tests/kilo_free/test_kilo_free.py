"""Kilo free pool: keyless, and only the slice the upstream marks free."""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_model_list_transform, get_shim

SHIM = "kilo_free--chat_completions"


@pytest.fixture()
def _registered(register):
    register("kilo_free")


def test_registers_with_its_base_url(_registered):
    shim = get_shim(SHIM)
    assert shim is not None
    assert shim.model_type == "llm"
    assert shim.format == "chat_completions"
    assert shim.connection.base_url == "https://api.kilo.ai/api/gateway"
    # The vendor manifest is a marker: every connection fact is on the leaf.
    assert shim.manifest is not None
    assert shim.manifest.connection == {}


def test_offers_only_the_free_slice(_registered):
    """The keyless lane refuses the paid models, so the picker must not list them."""
    transform = get_model_list_transform(SHIM)
    assert transform is not None
    entries = [
        {"id": "kilo-auto/free", "isFree": True},
        {"id": "cohere/north-mini-code:free", "isFree": True},
        {"id": "nvidia/nemotron-3-ultra", "isFree": False},
        {"isFree": True},  # no id
    ]
    ids, upstream = transform(entries)
    assert ids == ["kilo-auto/free", "cohere/north-mini-code:free"]
    assert upstream == {}
