"""Community and third-party vendor shims for llm-rosetta.

Each directory under ``providers/`` is one vendor, laid out exactly as core's
shim loader expects (``providers/<vendor>/<type>[/<format>]/provider.yaml``).
Every vendor has its own ``llm_rosetta.shim_providers`` entry point, named
after the directory and resolved through :mod:`llm_rosetta_shim_contrib.vendors`,
so core loads each one separately: a vendor that fails to load is logged by
core and the others still register.

Only :mod:`llm_rosetta.contracts` is imported here.  Core runs the entry points
during ``import llm_rosetta``, when :mod:`llm_rosetta.api` cannot be imported
yet.
"""

from __future__ import annotations

from pathlib import Path

from llm_rosetta.contracts.shim import ProviderShim, load_providers_from_dir

__version__ = "0.5.0"

#: The root of every vendor directory this package ships.
PROVIDERS_DIR = Path(__file__).parent / "providers"


def vendor_names() -> tuple[str, ...]:
    """Return the vendor directories this package ships, sorted.

    A vendor directory is a direct child of :data:`PROVIDERS_DIR` whose name
    does not start with ``_`` or ``.`` (the loader skips those too).
    """
    return tuple(
        sorted(
            d.name
            for d in PROVIDERS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(("_", "."))
        )
    )


def register_vendor(vendor: str) -> list[ProviderShim]:
    """Register the shims of one vendor directory.

    Args:
        vendor: A name from :func:`vendor_names`.

    Returns:
        The shims this call registered.

    Raises:
        ValueError: *vendor* is not a directory this package ships.
    """
    if vendor not in vendor_names():
        raise ValueError(f"llm-rosetta-shim-contrib ships no vendor {vendor!r}")
    return load_providers_from_dir(PROVIDERS_DIR, only_paths=(vendor,))


def register_shims() -> list[ProviderShim]:
    """Register every vendor this package ships.

    Not an entry point: core calls one entry point per vendor.  This is the
    convenience for a host that loads the whole package at once.  A vendor that
    fails raises, as :func:`load_providers_from_dir` does.
    """
    shims: list[ProviderShim] = []
    for vendor in vendor_names():
        shims.extend(register_vendor(vendor))
    return shims


__all__ = [
    "PROVIDERS_DIR",
    "register_shims",
    "register_vendor",
    "vendor_names",
]
