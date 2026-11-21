#!/usr/bin/env python3
"""Fail when a contrib shim name is also one of core's built-in shim names.

Shim names are location-independent (``type: <vendor>--<format>`` does not
change when a vendor moves between core and contrib), so two places must never
ship the same name: a gateway would have to pick one silently.  The gateway's
rule is that core wins; this check keeps contrib from publishing a name core
already owns.

Core's names come from the installed core itself: ``llm_rosetta.api`` lists the
registered shims, and ``plugin_source(name)`` is ``None`` exactly for those
loaded from core's own directory, so contrib (or any other plugin) being
installed in the same environment does not hide or fake a collision.  Contrib's
names come from the leaf ``provider.yaml`` files, read by
``scripts/build_shim_archive.py`` exactly as the manifest's ``shims`` field is.

A vendor directory that shares its name with a core vendor directory is
reported too, because the manifest and the gateway's selection key on it.

Usage::

    pip install "llm-rosetta @ git+https://github.com/Oaklight/llm-rosetta.git@master#subdirectory=packages/llm-rosetta"
    python scripts/check_core_collisions.py
    python scripts/check_core_collisions.py --allow opencode   # a planned move, core still has it
    python scripts/check_core_collisions.py --allow-file moves.txt   # one vendor per line

An allowed vendor that no longer overlaps core is reported on stderr (the
check still passes), so the allow list shrinks as core drops the vendors.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_archives():
    path = Path(__file__).resolve().with_name("build_shim_archive.py")
    spec = importlib.util.spec_from_file_location("build_shim_archive", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_allow_file(path: Path) -> list[str]:
    """Return the vendor names in *path*: one per line, ``#`` starts a comment."""
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def core_shim_names() -> tuple[str, set[str], set[str]]:
    """``(core version, built-in shim names, built-in vendor directory names)``."""
    from llm_rosetta.api import (
        __version__,
        builtin_providers_dir,
        list_shims,
        plugin_source,
    )

    names = {s.name for s in list_shims() if plugin_source(s.name) is None}
    vendors = {
        d.name
        for d in builtin_providers_dir().iterdir()
        if d.is_dir() and not d.name.startswith(("_", "."))
    }
    return __version__, names, vendors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="repository root")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="VENDOR",
        help="a contrib vendor allowed to overlap core (a move in progress)",
    )
    parser.add_argument(
        "--allow-file",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="a file of vendors allowed to overlap core, one per line",
    )
    args = parser.parse_args(argv)
    allowed = set(args.allow)
    for path in args.allow_file:
        allowed.update(read_allow_file(path))
    archives = _load_archives()
    root = (args.root or archives.repo_root()).resolve()
    vendors = {
        vendor: [name for name, _ in archives.declared_shims(vendor, root)]
        for vendor in archives.vendors(root)
    }

    version, core_names, core_vendors = core_shim_names()
    if not core_names:
        print(
            "error: core registered no built-in shims; the check would prove nothing",
            file=sys.stderr,
        )
        return 1
    problems: list[str] = []
    for vendor in sorted(allowed - set(vendors)):
        problems.append(f"allowed vendor {vendor!r} is not a contrib vendor")
    for vendor, shims in vendors.items():
        if vendor in allowed:
            if vendor not in core_vendors and not set(shims) & core_names:
                print(
                    f"note: allowed vendor {vendor!r} no longer overlaps core; "
                    "remove it from the allow list",
                    file=sys.stderr,
                )
            continue
        if vendor in core_vendors:
            problems.append(f"vendor directory {vendor!r} is also a core vendor")
        for shim in shims:
            if shim in core_names:
                problems.append(f"shim {shim!r} ({vendor}) is a core built-in")
    contrib_names = sum(len(shims) for shims in vendors.values())
    print(
        f"core {version}: {len(core_names)} built-in shims, {len(core_vendors)} vendor "
        f"directories; contrib: {contrib_names} shims in {len(vendors)} vendors"
    )
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1
    print("no collisions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
