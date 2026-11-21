"""The package layout: one vendor directory, one entry point, one record each.

These are the facts the manifest producer and core's loader both rely on, so a
vendor added by copying its directory fails here until it is complete.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None  # type: ignore[assignment]

from llm_rosetta_shim_contrib import register_vendor, vendor_names
from llm_rosetta_shim_contrib import vendors as vendor_entry_points

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src" / "llm_rosetta_shim_contrib"
_PROVIDERS = _SRC / "providers"
_GROUP = "llm_rosetta.shim_providers"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _source_vendors() -> list[str]:
    return sorted(
        d.name
        for d in _PROVIDERS.iterdir()
        if d.is_dir() and not d.name.startswith(("_", "."))
    )


def _declared_entry_points() -> dict[str, str]:
    if tomllib is None:
        pytest.skip("tomllib needs Python 3.11")
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["entry-points"][_GROUP]


def _leaves(vendor: str) -> list[Path]:
    root = _PROVIDERS / vendor
    return sorted(p for p in root.rglob("provider.yaml") if p.parent != root)


VENDORS = _source_vendors()


def _manifest_builder():
    """``scripts/build_manifest.py``, which owns the shim-name rule."""
    if "build_manifest" in sys.modules:
        return sys.modules["build_manifest"]
    path = _ROOT / "scripts" / "build_manifest.py"
    spec = importlib.util.spec_from_file_location("build_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_manifest"] = module
    spec.loader.exec_module(module)
    return module


manifest_builder = _manifest_builder()


def test_the_installed_package_ships_the_source_vendors():
    """A vendor left out of package-data would vanish from the wheel only."""
    assert list(vendor_names()) == VENDORS


def test_every_vendor_has_exactly_one_entry_point_named_after_it():
    expected = {v: f"llm_rosetta_shim_contrib.vendors:{v}" for v in VENDORS}
    assert _declared_entry_points() == expected


def test_the_installed_entry_points_match_the_vendors():
    from importlib.metadata import entry_points

    eps = entry_points(group=_GROUP)
    ours = sorted(
        ep.name for ep in eps if ep.value.startswith("llm_rosetta_shim_contrib.")
    )
    assert ours == VENDORS


@pytest.mark.parametrize("vendor", VENDORS)
def test_each_entry_point_callable_registers_only_its_vendor(register, vendor):
    from llm_rosetta.api import list_shims

    register(vendor)
    names = {s.name for s in list_shims()}
    assert names == {_load(leaf)["name"] for leaf in _leaves(vendor)}
    assert callable(getattr(vendor_entry_points, vendor))


def test_an_unknown_vendor_is_an_attribute_error():
    with pytest.raises(AttributeError):
        vendor_entry_points.no_such_vendor  # noqa: B018
    with pytest.raises(ValueError):
        register_vendor("no_such_vendor")


@pytest.mark.parametrize("vendor", VENDORS)
def test_every_leaf_is_named_after_its_vendor(vendor):
    """The vendor directory is the shim prefix the manifest and gateway key on.

    The part after ``--`` is usually the format, but not always: a vendor
    moved from core keeps the name core gave it (``zai--embedding`` has
    format ``openai``, ``zai--rerank`` format ``cohere``, and ``zhipu`` is
    the bare vendor key), because a shim name never changes when the vendor
    moves.  Same rule as core's manifest check: the vendor key,
    ``<vendor>--<name>`` or ``<vendor>_<lane>--<name>``, and the longest
    vendor key that matches owns the name.
    """
    leaves = _leaves(vendor)
    assert leaves, vendor
    for leaf in leaves:
        cfg = _load(leaf)
        name = cfg["name"]
        assert manifest_builder.shim_belongs_to(name, vendor), leaf
        # Within the package the longest vendor key owns a name, so kilo and
        # kilo_free (opencode and opencode_zen_free) never claim each other's.
        assert manifest_builder.shim_owner(name, VENDORS) == vendor, leaf


def test_vendors_toml_has_one_table_per_vendor():
    if tomllib is None:
        pytest.skip("tomllib needs Python 3.11")
    table = tomllib.loads((_ROOT / "vendors.toml").read_text(encoding="utf-8"))[
        "vendors"
    ]
    assert sorted(table) == VENDORS
    for vendor, entry in table.items():
        assert set(entry) >= {"version", "maturity", "since", "tags"}, vendor
        assert entry["maturity"] in {"experimental", "beta", "stable"}, vendor
        assert any(t.startswith("tier:") for t in entry["tags"]), vendor


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize(
    "path",
    sorted(_SRC.rglob("*.py")),
    ids=lambda p: p.relative_to(_SRC).as_posix(),
)
def test_package_code_reaches_core_only_through_the_contracts(path):
    """Entry points and sidecars run during ``import llm_rosetta``.

    ``llm_rosetta.api`` cannot be imported then, and any other core module is
    not a promise; ``llm_rosetta.contracts`` is the surface the manifest's
    ``requires.surface`` versions.
    """
    core = {
        m
        for m in _imported_modules(path)
        if m == "llm_rosetta" or m.startswith("llm_rosetta.")
    }
    assert all(m.startswith("llm_rosetta.contracts") for m in core), sorted(core)


_PROBE = textwrap.dedent(
    """
    import sys
    from llm_rosetta.api import get_shim
    missing = [name for name in sys.argv[1:] if get_shim(name) is None]
    print(" ".join(missing))
    """
)


def _all_shim_names() -> list[str]:
    return sorted(_load(leaf)["name"] for v in VENDORS for leaf in _leaves(v))


def test_every_vendor_registers_inside_the_core_import():
    """Core runs the entry points during ``import llm_rosetta``.

    The in-process tests call the loaders after core finished importing, so
    only a fresh interpreter shows an entry point that fails at that moment.
    """
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, *_all_shim_names()],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Failed to load plugin shim entry point" not in proc.stderr, proc.stderr
    assert proc.stdout.split() == []


def test_a_failing_entry_point_does_not_stop_the_vendors(tmp_path):
    """One broken entry point in the group is logged; every vendor still loads.

    A throwaway distribution declares an entry point that raises on load and
    sorts ahead of the vendors, so the loop meets it first.
    """
    dist = tmp_path / "aaa_broken_shim-0.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: aaa-broken-shim\nVersion: 0.0.0\n"
    )
    (dist / "entry_points.txt").write_text(
        f"[{_GROUP}]\naaa_broken = llm_rosetta_shim_contrib.vendors:no_such_vendor\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(tmp_path), env.get("PYTHONPATH", "")) if p
    )
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, *_all_shim_names()],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert "Failed to load plugin shim entry point: aaa_broken" in proc.stderr
    assert proc.stdout.split() == []


def test_a_broken_vendor_does_not_stop_its_siblings(tmp_path, monkeypatch, register):
    """Each vendor's entry point loads only its own directory.

    Core calls every entry point inside its own ``try`` (the test above shows
    that against the real core import); this shows the other half: a vendor
    whose ``transforms.py`` raises on import fails its own entry point and no
    other.
    """
    from importlib.metadata import entry_points

    import llm_rosetta_shim_contrib
    from llm_rosetta.api import list_shims

    broken = tmp_path / "providers"
    shutil.copytree(_PROVIDERS, broken, ignore=shutil.ignore_patterns("__pycache__"))
    (broken / "llm7" / "llm" / "transforms.py").write_text(
        "raise RuntimeError('broken')\n"
    )
    monkeypatch.setattr(llm_rosetta_shim_contrib, "PROVIDERS_DIR", broken)

    eps = [
        ep
        for ep in entry_points(group=_GROUP)
        if ep.value.startswith("llm_rosetta_shim_contrib.")
    ]
    failed: list[str] = []
    register()  # a clean registry, restored afterwards
    for ep in eps:
        try:
            ep.load()()
        except Exception:  # noqa: BLE001 - the loop core runs
            failed.append(ep.name)
    assert failed == ["llm7"]
    registered = {s.name for s in list_shims()}
    expected = {
        _load(leaf)["name"] for v in VENDORS if v != "llm7" for leaf in _leaves(v)
    }
    assert registered == expected
