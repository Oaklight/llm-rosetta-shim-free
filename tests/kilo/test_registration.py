"""Kilo shim: the paid gateway lane.

Ported from llm-rosetta tests/test_shims.py (TestFreeSourceShim) and
tests/test_shim_loader.py (TestDeclaredGrouping) (#1660 S7).
"""

from __future__ import annotations

import pytest

from llm_rosetta.api import get_model_list_transform, get_shim


@pytest.fixture()
def _registered(register):
    register("kilo")


def test_registers_the_chat_lane(_registered):
    shim = get_shim("kilo--chat_completions")
    assert shim is not None
    assert shim.name == "kilo--chat_completions"
    assert shim.model_type == "llm"
    assert shim.format == "chat_completions"


def test_kilo_shim_is_the_paid_lane(_registered):
    """The keyless free pool is a separate, externally published shim.

    Keeping them apart is what lets this leaf demand a credential: a provider
    on it without a key is refused rather than sent upstream unauthenticated.
    """
    shim = get_shim("kilo--chat_completions")

    assert shim is not None
    assert shim.format == "chat_completions"
    assert shim.free_source is False
    assert shim.connection.keyless is False
    assert shim.connection.api_key_env == "KILO_API_KEY"
    assert shim.connection.models_path == "/models"
    # The brand is the group title; the shim's own row label is unset, so the
    # picker shows it as the bare base format under "Kilo".
    assert shim.group_label == "Kilo"
    assert shim.group is None
    assert shim.display_name is None
    assert shim.logo is not None
    # No model-list filter: a paid account sees the whole catalogue.
    assert get_model_list_transform("kilo--chat_completions") is None
