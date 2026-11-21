"""The manifest producer: archives, records, append-only history, validation.

``scripts/build_shim_archive.py`` and ``scripts/build_manifest.py`` are the
same builder the argonne repository publishes with (only the package, source
and repository constants differ), so both repositories write one format.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
_COMMIT = "0" * 40
_STAMP = "2026-11-21T00:00:00Z"


def _module(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


archives = _module("build_shim_archive")
builder = _module("build_manifest")
collisions = _module("check_core_collisions")

needs_tomllib = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="the builder reads vendors.toml with tomllib"
)

VENDORS = archives.vendors(_ROOT)
FREE = ["kilo_free", "llm7", "opencode_zen_free", "ovhcloud"]


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A copy of the package tree and vendors.toml, safe to edit."""
    root = tmp_path / "repo"
    shutil.copytree(
        _ROOT / "src",
        root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    shutil.copy(_ROOT / "vendors.toml", root / "vendors.toml")
    return root


def _build(root: Path = _ROOT, previous=None):
    return builder.build_manifest(
        root, previous=previous, commit=_COMMIT, generated_at=_STAMP
    )


@needs_tomllib
def test_the_repository_builds_a_valid_manifest():
    manifest, added = _build()
    assert builder.validate_manifest(manifest) == []
    assert manifest["source"] == "contrib"
    assert manifest["repo"] == "https://github.com/Oaklight/llm-rosetta-shim-contrib"
    assert sorted(manifest["vendors"]) == VENDORS
    for vendor, entry in manifest["vendors"].items():
        (record,) = entry["versions"]
        assert record["requires"] == {"surface": 1, "ir": 1}
        assert record["archive"] == f"{record['version']}/{vendor}.tar.gz"
        assert record["sha256"] == archives.sha256_hex(added[record["archive"]])
        assert record["shims"] == [n for n, _ in archives.declared_shims(vendor, _ROOT)]
        assert record["conformance"] == {"date": None, "result": "none"}
        assert record["promoted_to"] is None


@needs_tomllib
def test_tags_and_maturity_come_from_vendors_toml():
    vendors = _build()[0]["vendors"]
    for free in FREE:
        assert vendors[free]["versions"][0]["tags"] == ["tier:free"]
    assert vendors["opendesign"]["versions"][0]["tags"] == [
        "tier:subscription",
        "auth:device",
    ]
    # The model makers' own APIs moved from core are the promotion candidates
    # (Oaklight/llm-rosetta#1660, "Placement"); everything else is beta.
    stable = {v for v, e in vendors.items() if e["versions"][0]["maturity"] == "stable"}
    assert stable == {
        "moonshot",
        "qwen",
        "volcengine",
        "xai",
        "zai",
        "zhipu",
    }
    assert {
        e["versions"][0]["maturity"] for v, e in vendors.items() if v not in stable
    } == {"beta"}
    assert vendors["openai_chatgpt"]["versions"][0]["tags"] == [
        "tier:subscription",
        "auth:oauth",
    ]


@needs_tomllib
def test_the_installed_core_satisfies_every_requires():
    """The gateway's rule: surface equal, ir not above the running core's."""
    from llm_rosetta.contracts import IR_VERSION, SURFACE_VERSION

    for entry in _build()[0]["vendors"].values():
        requires = entry["versions"][0]["requires"]
        assert requires["surface"] == SURFACE_VERSION
        assert requires["ir"] <= IR_VERSION


@needs_tomllib
def test_vendors_toml_must_name_every_vendor(tree: Path):
    text = (tree / "vendors.toml").read_text()
    (tree / "vendors.toml").write_text(
        text.replace("[vendors.llm7]", "[vendors.seven]")
    )
    with pytest.raises(builder.ManifestError, match="disagree"):
        _build(tree)


def test_the_build_is_byte_reproducible():
    for vendor in VENDORS:
        assert archives.build_archive(vendor, _ROOT) == archives.build_archive(
            vendor, _ROOT
        )


def test_an_archive_holds_one_vendor_under_providers():
    data = archives.build_archive("opendesign", _ROOT)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
        shims_yaml = tar.extractfile("providers/shims.yaml").read().decode()
    assert all(
        n == "providers/shims.yaml" or n.startswith("providers/opendesign/")
        for n in names
    )
    assert "providers/opendesign/auth.py" in names
    assert 'core: ">=0.14.0"' in shims_yaml
    assert "opendesign--messages" in shims_yaml
    assert "llm7" not in shims_yaml


def test_bytecode_caches_stay_out(tree: Path):
    cache = archives.providers_dir(tree) / "llm7" / "llm" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "transforms.cpython-312.pyc").write_bytes(b"\0")
    assert archives.build_archive("llm7", tree) == archives.build_archive("llm7", _ROOT)


def test_a_leaf_missing_from_the_package_shims_yaml_fails_the_build(tree: Path):
    shims = archives.providers_dir(tree) / "shims.yaml"
    shims.write_text(
        shims.read_text().replace(
            "  - name: llm7--chat_completions\n    path: llm7/llm\n", ""
        )
    )
    with pytest.raises(archives.ArchiveError, match="does not match the llm7 leaves"):
        archives.build_archive("llm7", tree)


@needs_tomllib
def test_an_unchanged_vendor_keeps_its_published_record(tree: Path):
    first, _ = _build(tree)
    old = copy.deepcopy(first)
    for entry in old["vendors"].values():
        entry["versions"][0]["commit"] = "1" * 40
    second, added = _build(tree, previous=old)
    assert added == {}
    assert second["vendors"] == old["vendors"]


@needs_tomllib
def test_a_changed_vendor_without_a_bump_is_refused(tree: Path):
    previous, _ = _build(tree)
    leaf = archives.providers_dir(tree) / "llm7" / "llm" / "provider.yaml"
    leaf.write_text(leaf.read_text() + "\n# changed\n")
    with pytest.raises(builder.ManifestError, match="Bump vendors.llm7.version"):
        _build(tree, previous=previous)


@needs_tomllib
def test_a_bumped_vendor_is_prepended(tree: Path):
    previous, _ = _build(tree)
    toml = tree / "vendors.toml"
    toml.write_text(
        toml.read_text().replace(
            '[vendors.llm7]\nversion = "0.4.0"', '[vendors.llm7]\nversion = "0.4.1"'
        )
    )
    leaf = archives.providers_dir(tree) / "llm7" / "llm" / "provider.yaml"
    leaf.write_text(leaf.read_text() + "\n# changed\n")
    manifest, added = _build(tree, previous=previous)
    versions = [r["version"] for r in manifest["vendors"]["llm7"]["versions"]]
    assert versions == ["0.4.1", "0.4.0"]
    assert list(added) == ["0.4.1/llm7.tar.gz"]
    assert (
        manifest["vendors"]["llm7"]["versions"][1]
        == previous["vendors"]["llm7"]["versions"][0]
    )


@needs_tomllib
def test_a_vendor_that_left_the_tree_keeps_its_history(tree: Path):
    previous, _ = _build(tree)
    shutil.rmtree(archives.providers_dir(tree) / "ovhcloud")
    shims = archives.providers_dir(tree) / "shims.yaml"
    shims.write_text(
        shims.read_text().replace(
            "  - name: ovhcloud--chat_completions\n    path: ovhcloud/llm\n", ""
        )
    )
    toml = tree / "vendors.toml"
    text = toml.read_text()
    toml.write_text(
        text[: text.index("[vendors.ovhcloud]")] + text[text.index("# Open Design") :]
    )
    manifest, _ = _build(tree, previous=previous)
    assert manifest["vendors"]["ovhcloud"] == previous["vendors"]["ovhcloud"]


@needs_tomllib
def test_write_outputs_lays_out_the_dist_tree(tree: Path, tmp_path: Path):
    out = tmp_path / "out"
    manifest, added = _build(tree)
    builder.write_outputs(out, manifest, added, "0.4.0")
    assert json.loads((out / "manifest.json").read_text()) == manifest
    assert (out / "0.4.0" / "manifest.json").read_text() == (
        out / "manifest.json"
    ).read_text()
    for rel in added:
        line = (out / f"{rel}.sha256").read_text()
        assert line.split()[0] == archives.sha256_hex((out / rel).read_bytes())
    changed = copy.deepcopy(manifest)
    changed["generated_at"] = "2026-11-22T00:00:00Z"
    with pytest.raises(builder.ManifestError, match="already published"):
        builder.write_outputs(out, changed, {}, "0.4.0")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("vendors", "llm7", "versions", 0, "maturity"), "gold", "maturity"),
        (("vendors", "llm7", "versions", 0, "requires"), {"surface": 1}, "requires"),
        (("vendors", "llm7", "versions", 0, "sha256"), "abc", "sha256"),
        (
            ("vendors", "llm7", "versions", 0, "shims"),
            ["ovhcloud--chat_completions"],
            "must be 'llm7', 'llm7--<name>' or 'llm7_<lane>--<name>'",
        ),
        (
            # A shared prefix is not the vendor: ``llm7x`` is neither the key
            # nor ``llm7--...``.
            ("vendors", "llm7", "versions", 0, "shims"),
            ["llm7x--chat_completions"],
            "must be 'llm7', 'llm7--<name>' or 'llm7_<lane>--<name>'",
        ),
        (
            ("vendors", "llm7", "versions", 0, "shims"),
            ["ovhcloud"],
            "must be 'llm7', 'llm7--<name>' or 'llm7_<lane>--<name>'",
        ),
        (
            ("vendors", "llm7", "versions", 0, "conformance"),
            {"date": None, "result": "pass"},
            "needs a date",
        ),
        (("vendors", "llm7", "versions", 0, "archive"), "0.4.0/x.tar.gz", "archive"),
        (("vendors", "llm7", "versions", 0, "promoted_to"), "core", "promoted_to"),
        (("manifest_version",), 2, "manifest_version"),
        (("generated_at",), "yesterday", "generated_at"),
    ],
)
@needs_tomllib
def test_the_validator_rejects_a_broken_field(path, value, message):
    doc = copy.deepcopy(_build()[0])
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    errors = builder.validate_manifest(doc)
    assert any(message in e for e in errors), errors


@needs_tomllib
def test_the_cli_dry_run_validates_and_check_accepts_it(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "build_manifest.py"),
            "--dry-run",
            "--commit",
            _COMMIT,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "dry-run: ok" in proc.stderr
    path = tmp_path / "manifest.json"
    path.write_text(proc.stdout)
    check = subprocess.run(
        [sys.executable, str(_SCRIPTS / "build_manifest.py"), "--check", str(path)],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


@needs_tomllib
def test_the_cli_refuses_a_tag_that_is_not_the_package_version(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "build_manifest.py"),
            "--out",
            str(tmp_path),
            "--expect-version",
            "9.9.9",
            "--commit",
            _COMMIT,
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "tag says 9.9.9" in proc.stderr


_LOAD_ARCHIVE = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from llm_rosetta.api import list_shims, staging_registry
    from llm_rosetta.contracts.shim import load_providers_from_dir
    with staging_registry():
        load_providers_from_dir(Path(sys.argv[1]), on_error="raise")
    print(" ".join(sorted(s.name for s in list_shims())))
    """
)


@pytest.mark.parametrize("vendor", VENDORS)
def test_each_archive_loads_with_core_in_a_fresh_interpreter(vendor, tmp_path: Path):
    """What a gateway does with a downloaded archive: extract, then load providers/."""
    data = archives.build_archive(vendor, _ROOT)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(tmp_path, **safe)
    proc = subprocess.run(
        [sys.executable, "-c", _LOAD_ARCHIVE, str(tmp_path / "providers")],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = sorted(n for n, _ in archives.declared_shims(vendor, _ROOT))
    assert proc.stdout.split() == expected


def test_contrib_shares_no_shim_name_with_the_installed_core(capsys):
    """CI's call: no allowances."""
    assert collisions.main([]) == 0
    assert "no collisions" in capsys.readouterr().out


def test_an_allow_file_is_read_one_vendor_per_line(tmp_path, monkeypatch, capsys):
    allow = tmp_path / "moves.txt"
    allow.write_text("# a planned move\nllm7\n\n", encoding="utf-8")
    assert collisions.read_allow_file(allow) == ["llm7"]
    monkeypatch.setattr(
        collisions,
        "core_shim_names",
        lambda: ("0.0.0", {"llm7--chat_completions", "x--y"}, {"x"}),
    )
    assert collisions.main([]) == 1
    assert collisions.main(["--allow-file", str(allow)]) == 0


def test_an_allowed_vendor_that_no_longer_overlaps_is_reported(monkeypatch, capsys):
    """Once core drops a vendor, the check says its allow entry can go."""
    monkeypatch.setattr(
        collisions, "core_shim_names", lambda: ("0.0.0", {"x--y"}, {"x"})
    )
    assert collisions.main(["--allow", "llm7"]) == 0
    assert "allowed vendor 'llm7' no longer overlaps core" in capsys.readouterr().err


def test_a_collision_with_core_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        collisions,
        "core_shim_names",
        lambda: ("0.0.0", {"llm7--chat_completions", "x--y"}, {"x"}),
    )
    assert collisions.main([]) == 1
    assert (
        "shim 'llm7--chat_completions' (llm7) is a core built-in"
        in capsys.readouterr().err
    )
    assert collisions.main(["--allow", "llm7"]) == 0


def test_a_vendor_directory_shared_with_core_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        collisions, "core_shim_names", lambda: ("0.0.0", {"x--y"}, {"opendesign"})
    )
    assert collisions.main([]) == 1
    assert (
        "vendor directory 'opendesign' is also a core vendor" in capsys.readouterr().err
    )


@needs_tomllib
def test_a_bare_vendor_key_is_a_shim_name():
    """Vendors moved from core keep bare chat shim names (``zhipu``); the rule
    is the one core's manifest check adopts: the vendor key, or ``<vendor>--``.
    """
    manifest = _build()[0]
    record = manifest["vendors"]["llm7"]["versions"][0]
    record["shims"] = ["llm7", "llm7--chat_completions"]
    assert builder.validate_manifest(manifest) == []
    assert "zhipu" in manifest["vendors"]["zhipu"]["versions"][0]["shims"]


@needs_tomllib
def test_a_lane_qualified_name_belongs_to_its_vendor():
    """``<vendor>_<lane>--<name>`` is the vendor's (core's rule: alcf_sophia)."""
    manifest = _build()[0]
    manifest["vendors"]["llm7"]["versions"][0]["shims"] = ["llm7_eu--chat_completions"]
    assert builder.validate_manifest(manifest) == []


@needs_tomllib
def test_the_longest_vendor_key_of_the_manifest_owns_a_name():
    """kilo and kilo_free are both vendors: kilo may not publish kilo_free's."""
    manifest = _build()[0]
    kilo = manifest["vendors"]["kilo"]["versions"][0]
    kilo["shims"] = ["kilo--chat_completions", "kilo_free--chat_completions"]
    problems = builder.validate_manifest(manifest)
    assert problems == [
        "vendors.kilo.versions[0].shims: 'kilo_free--chat_completions' "
        "belongs to vendor 'kilo_free' of this manifest"
    ]


@pytest.mark.parametrize(
    ("name", "owner"),
    [
        ("kilo--chat_completions", "kilo"),
        ("kilo_free--chat_completions", "kilo_free"),
        ("opencode--messages", "opencode"),
        ("opencode_zen_free--chat_completions", "opencode_zen_free"),
        ("zhipu", "zhipu"),
        ("zhipu--rerank", "zhipu"),
        ("kilox--chat_completions", None),
    ],
)
def test_shim_owner(name, owner):
    keys = ["kilo", "kilo_free", "opencode", "opencode_zen_free", "zhipu"]
    assert builder.shim_owner(name, keys) == owner
