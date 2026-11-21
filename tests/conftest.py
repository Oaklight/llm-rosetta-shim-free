"""Shared fixtures: a clean shim registry holding only the vendors a test loads."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import pytest
from llm_rosetta.api import restore_registry, snapshot_registry, staging_registry

from llm_rosetta_shim_contrib import register_vendor


@pytest.fixture()
def register() -> Iterator[Callable[..., None]]:
    """Return ``register(*vendors)``: load those vendors into a clean registry.

    The registry the test found is restored afterwards.
    """
    saved = snapshot_registry()

    def _register(*vendors: str) -> None:
        with staging_registry():  # starts empty: only these vendors are present
            for vendor in vendors:
                register_vendor(vendor)

    yield _register
    restore_registry(saved)
