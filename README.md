# llm-rosetta-shim-contrib

Vendor shims for [llm-rosetta](https://github.com/Oaklight/llm-rosetta) that do not ship with core: free endpoints, sign-in and subscription lanes, aggregators, and new vendors on their way to core. One directory per vendor, each published as its own versioned archive through one manifest, so a gateway installs only the vendors it selects and only versions its core can load.

This repository was `llm-rosetta-shim-free` (renamed 2026-11-21; history, issues and redirects kept). `llm-rosetta-shim-opendesign` was merged into it with its history. The plan is Oaklight/llm-rosetta#1660.

## Vendors

| Vendor | Shims | Tags | Maturity | Notes |
|:---|:---|:---|:---|:---|
| `kilo_free` | `kilo_free--chat_completions` | `tier:free` | beta | [free tier](docs/vendors/free-tier.md) |
| `llm7` | `llm7--chat_completions` | `tier:free` | beta | [free tier](docs/vendors/free-tier.md) |
| `opencode_zen_free` | `opencode_zen_free--chat_completions` | `tier:free` | beta | [free tier](docs/vendors/free-tier.md) |
| `ovhcloud` | `ovhcloud--chat_completions` | `tier:free` | beta | [free tier](docs/vendors/free-tier.md) |
| `opendesign` | `opendesign--chat_completions`, `opendesign--open_responses`, `opendesign--messages` | `tier:subscription`, `auth:device` | beta | [Open Design Cloud](docs/vendors/opendesign.md) |
| `opencode` | `opencode--chat_completions`, `opencode--messages`, `opencode--open_responses` | `tier:subscription`, `tier:paid` | beta | Go and Zen lanes; Go allowance probe `opencode_go` |
| `openai_chatgpt` | `openai_chatgpt--open_responses` | `tier:subscription`, `auth:oauth` | beta | Sign in with ChatGPT; in-band probe `openai_codex` |
| `antigravity` | `antigravity--acp` | `tier:subscription`, `auth:cli` | beta | drives the local `agy` CLI over ACP |
| `kilo` | `kilo--chat_completions` | `tier:paid` | beta | aggregator (the keyless pool is `kilo_free`) |
| `openrouter` | `openrouter--chat_completions`, `openrouter--messages`, `openrouter--open_responses`, `openrouter--rerank` | `tier:paid` | beta | aggregator |
| `groq` | `groq--chat_completions` | `tier:paid` | beta | |
| `nvidia` | `nvidia--chat_completions` | `tier:paid` | beta | NIM hosted endpoints |
| `siliconflow` | `siliconflow--chat_completions`, `siliconflow--embedding`, `siliconflow--rerank` | `tier:paid`, `region:cn` | beta | |
| `modelscope` | `modelscope--chat_completions` | `tier:paid`, `region:cn` | beta | |
| `zai` | `zai--chat_completions`, `zai--messages`, `zai--embedding`, `zai--rerank` | `tier:paid` | stable | promotion candidate |
| `volcengine` | `volcengine--chat_completions`, `volcengine--open_responses`, `volcengine--embedding` | `tier:paid`, `region:cn` | stable | promotion candidate |
| `zhipu` | `zhipu`, `zhipu--embedding`, `zhipu--rerank` | `tier:paid`, `region:cn` | stable | promotion candidate; mainland region of `zai` |
| `xai` | `xai` | `tier:paid` | stable | promotion candidate |
| `qwen` | `qwen` | `tier:paid`, `region:cn` | stable | promotion candidate |
| `moonshot` | `moonshot` | `tier:paid`, `region:cn` | stable | promotion candidate |

The vendors from `opencode` down moved out of llm-rosetta core (Oaklight/llm-rosetta#1660 S7) with their shim names unchanged; `tier:paid` there means a keyed account, some with a free allowance. `zhipu`, `xai`, `qwen` and `moonshot` keep their bare chat shim names (a shim name is the vendor key or starts with `<vendor>--`).

The free-tier vendors are third-party services collected from public sources. Read the disclaimer in [docs/vendors/free-tier.md](docs/vendors/free-tier.md) before you use them: nothing here guarantees data retention terms, and the upstream owns its terms and limits.

## Where a shim lives: core or contrib

A shim belongs in core only when both hold:

1. It is the model maker's own API (not an aggregator, reseller or mirror).
2. It authenticates with a static API key only: no `auth.py`. A `quota.py` is allowed when its probe uses only that key.

Everything else lives in contrib permanently: OAuth, device sign-in and subscription lanes, aggregators and free endpoints. Eligibility is necessary, not sufficient: a new or rarely used shim starts in contrib and is promoted when it is mature.

Shim names do not depend on the location. `type: <vendor>--<format>` stays the same when a vendor moves between core and contrib, so a promotion or a demotion changes where the gateway installs it from, never a user's config. CI fails when a contrib shim name is also a core built-in (`scripts/check_core_collisions.py`).

## Maturity ladder

| Stage | Where | Meaning |
|:---|:---|:---|
| `experimental` | contrib | New, or the upstream API is still changing; no stability promise |
| `beta` | contrib | Has tests and one live verification; the shim may still change |
| `stable` | contrib | Meets the promotion criteria; candidate for core |
| core | core | Ships with core, under core's compatibility rules |

The stage is recorded per vendor in the manifest (`maturity`, `since`, and the last `conformance` result).

Promotion into core needs all of: eligible under the placement rule; `stable` in contrib for at least one minor release cycle; a live `tools/conformance` run for each of its formats passed within the last 30 days; no shim-caused bug fix in the last 4 weeks and no open bug; registration and transform tests here and a docs entry; a reviewed PR. Evidence of real use is advisory.

Demotion back to contrib needs any one of: the vendor changes its auth so it is no longer a plain API key; a conformance failure stays unfixed for one minor cycle; no evidence of use and no maintainer for two minor cycles.

## Install a vendor in the gateway

A gateway that reads manifests (Oaklight/llm-rosetta#1660 S2) takes a list of sources and a selection:

```jsonc
{
  "shims": {
    "sources": ["contrib"],                    // catalogue ids or manifest URLs
    "install": ["opendesign", "tag:free"]      // vendor names, tags, or "contrib:*"
  },
  "providers": {
    "opendesign": { "type": "opendesign--chat_completions" },
    "llm7-free": { "type": "llm7--chat_completions" }
  }
}
```

For each selected vendor the gateway installs the newest version whose `requires` matches its core (`requires.surface == SURFACE_VERSION`, `requires.ir <= IR_VERSION`), pinned by the archive's sha256, and upgrades only when a newer compatible version is published. When core already registers a shim name, core wins and the gateway logs the source it ignored. The old `"presets": ["free"]` and `"presets": ["opendesign"]` keys map to `contrib` with `tag:free` and `opendesign`, so no config edit is needed.

The manifest is published on the `dist` branch:

- `https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-contrib@dist/manifest.json` (default)
- `https://raw.githubusercontent.com/Oaklight/llm-rosetta-shim-contrib/dist/manifest.json` (fallback)

Installing the Python distribution also works: `pip install llm-rosetta-shim-contrib` registers every vendor through one `llm_rosetta.shim_providers` entry point per vendor. Core calls each entry point separately, so a vendor that fails to load is logged and the others still register.

## Layout

```
src/llm_rosetta_shim_contrib/
  __init__.py            register_vendor(), vendor_names(); imports llm_rosetta.contracts only
  vendors.py             the entry-point callables, one per vendor directory
  providers/
    shims.yaml           every shim and its directory (checked against the leaves)
    <vendor>/
      provider.yaml      vendor manifest (connection defaults, logo)
      auth.py, quota.py  optional sidecars
      llm/[<format>/]provider.yaml, transforms.py
tests/<vendor>/          the vendor's own tests
vendors.toml             release metadata per vendor: version, maturity, since, tags
tests/*.py               layout, free-tier rules, manifest producer, collision check
scripts/build_shim_archive.py, scripts/build_manifest.py
scripts/check_core_collisions.py
```

Package code imports core only through `llm_rosetta.contracts`: core runs the entry points and loads the sidecars during `import llm_rosetta`, when `llm_rosetta.api` cannot be imported yet. Tests use `llm_rosetta.api`. `tests/test_layout.py` enforces both.

### Add a vendor

1. Copy the vendor directory to `src/llm_rosetta_shim_contrib/providers/<vendor>/`. Every leaf must be named `<vendor>--<name>` (a new vendor uses the format as `<name>`) or, for a vendor moved from core, the name core gave it, which may be the bare vendor key.
2. Add a `[vendors.<vendor>]` table to `vendors.toml` (`version`, `maturity`, `since`, `tags`; optional `conformance`, `requires`, `promoted_to`).
3. Add one line to `[project.entry-points."llm_rosetta.shim_providers"]` in `pyproject.toml`: `<vendor> = "llm_rosetta_shim_contrib.vendors:<vendor>"`.
4. Move its tests to `tests/<vendor>/`.
5. Add its leaves to `src/llm_rosetta_shim_contrib/providers/shims.yaml`, then run `pytest` and `python scripts/build_manifest.py --dry-run`.

## Versions and releases

Each vendor has its own version, in its `[vendors.<vendor>]` table of the repository-root `vendors.toml`, together with its maturity, `since` date and tags; the top-level `[requires]` table sets the `{surface, ir}` floor. The metadata is kept out of the vendor's `provider.yaml` for two reasons: core's loader refuses keys it does not know in a vendor manifest, and a version inside the archive would change the archive's bytes on every metadata edit. Bump a vendor's version whenever anything under its directory changes. The argonne repository uses the same file and the same builder scripts, so both publish one format.

A `v*` tag (equal to the package `__version__`) runs `.github/workflows/release.yml`, which runs `scripts/build_manifest.py --out <dist checkout> --previous <dist>/manifest.json` and pushes:

- `dist/<version>/<vendor>.tar.gz` and `.sha256`, for each vendor version not yet published. The archive root is `providers/`, holding `providers/<vendor>/…` exactly as core's loader expects and a `providers/shims.yaml` for that vendor. Archives are byte-reproducible.
- `dist/<release>/manifest.json` (immutable) and `dist/manifest.json` (latest).

Published versions are append-only: a vendor whose version is already published keeps its record, and the build fails if its archive changed without a version bump. CI runs the same build as a dry run on every push and pull request, against the manifest already on `dist`. The release also attaches the new archives and the release manifest to a GitHub Release for the tag.

A manifest record:

```json
{
  "version": "0.3.0",
  "commit": "<40-hex>",
  "archive": "0.3.0/opendesign.tar.gz",
  "sha256": "<64-hex>",
  "requires": {"surface": 1, "ir": 1},
  "shims": ["opendesign--chat_completions", "opendesign--messages", "opendesign--open_responses"],
  "tags": ["tier:subscription", "auth:device"],
  "maturity": "beta",
  "since": "2026-11-14",
  "conformance": {"date": null, "result": "none"},
  "promoted_to": null
}
```

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install "llm-rosetta @ git+https://github.com/Oaklight/llm-rosetta.git@master#subdirectory=packages/llm-rosetta"
pip install . pytest pyyaml
pytest
python scripts/build_shim_archive.py         # archive layout check
python scripts/build_manifest.py --dry-run   # build and validate, print the manifest
python scripts/check_core_collisions.py
```

Requires Python >= 3.10 and `llm-rosetta >= 0.14.0.dev35` (the first core with `llm_rosetta.contracts`). The manifest builder needs Python 3.11+ (`tomllib`).

## License

MIT.
