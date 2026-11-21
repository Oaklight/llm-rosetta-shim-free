"""One entry-point callable per vendor directory.

``pyproject.toml`` declares one ``llm_rosetta.shim_providers`` entry point per
vendor, ``<vendor> = "llm_rosetta_shim_contrib.vendors:<vendor>"``.  Core loads
and calls each entry point inside its own ``try``, so one vendor that fails
(a bad ``provider.yaml``, a sidecar that does not import) is logged and skipped
while the others register.

The callables are produced on attribute access (PEP 562), so adding a vendor
means adding its directory and its entry-point line; nothing here changes.
A name that is not a shipped vendor directory is an ``AttributeError``, which
is what ``EntryPoint.load()`` reports for a missing attribute.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from llm_rosetta.contracts.shim import ProviderShim

from . import register_vendor, vendor_names


def __getattr__(name: str) -> Callable[[], list[ProviderShim]]:
    if name.startswith("_") or name not in vendor_names():
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    loader = partial(register_vendor, name)
    loader.__doc__ = f"Register the {name} vendor's shims (entry point)."
    return loader


def __dir__() -> list[str]:
    return sorted(vendor_names())
