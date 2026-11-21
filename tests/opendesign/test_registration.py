"""The plugin registers the three Open Design Cloud shims."""

from __future__ import annotations

import pytest

from llm_rosetta.api import (
    get_shim,
    restore_registry,
    snapshot_registry,
    staging_registry,
)

from llm_rosetta_shim_contrib import register_vendor

_SHIMS = {
    "opendesign--chat_completions": "chat_completions",
    "opendesign--open_responses": "open_responses",
    "opendesign--messages": "messages",
}


@pytest.fixture()
def _registered():
    saved = snapshot_registry()
    with staging_registry():  # clean registry, so only the plugin's shims are present
        register_vendor("opendesign")
    yield
    restore_registry(saved)


def test_registers_the_three_formats(_registered):
    for name, base in _SHIMS.items():
        shim = get_shim(name)
        assert shim is not None, name
        assert shim.name == name
        assert shim.model_type == "llm"
        assert shim.format == base


def test_the_vendor_manifest_supplies_the_mark(_registered):
    """Every lane shows the vendor's mark without restating it."""
    expected = (
        "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-opendesign@main/"
        "assets/opendesign.svg"
    )
    for name in _SHIMS:
        assert get_shim(name).logo == expected, name


def test_the_vendor_manifest_supplies_the_connection_defaults(_registered):
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.manifest is not None, name
        assert shim.connection.base_url == "https://amr-link.open-design.ai/v1"
        assert shim.connection.api_key_env is None
        assert (
            shim.connection.models_path == "https://amr-link.open-design.ai/v1/models"
        )
        assert shim.connection.manage_usage_url == "https://open-design.ai/cloud/usage"


def test_the_vendor_ships_one_device_sign_in_exchange(_registered):
    """Every lane inherits the vendor's exchange, not a copy of it."""
    exchanges = set()
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.auth is not None, name
        assert shim.auth.kind == "device", name
        assert callable(shim.auth.credential), name
        assert shim.auth.can_begin_login(), name
        assert shim.auth.can_complete_login(), name
        exchanges.add(id(shim.auth))
    assert len(exchanges) == 1


def test_the_allowance_is_read_with_the_control_credential(_registered):
    """The plan is read on the control plane, with the sign-in's second key."""
    for name in _SHIMS:
        shim = get_shim(name)
        assert shim.quota is not None, name
        assert shim.quota.probe == "opendesign", name
        assert [probe.id for probe in shim.quota_probes] == ["opendesign"], name
        # The role is what makes the reading advisory on the gateway side.
        assert shim.quota_probes[0].credential_role == "control", name
