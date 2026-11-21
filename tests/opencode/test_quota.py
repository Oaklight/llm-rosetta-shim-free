"""The OpenCode Go quota probe.

Ported from llm-rosetta tests/gateway/test_quota.py (#1660 S7): the probe-only
parts of ``TestOpenCodeGoProbe`` and ``TestProbeResolution``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from llm_rosetta.contracts.quota import QuotaProbeError, resolve_probe

from llm_rosetta_shim_contrib.providers.opencode.quota import (
    PROBES,
    OpenCodeGoProbe,
)

# The probes ship with the shims; a test resolves against them directly.
_PROBES = (OpenCodeGoProbe(),)


class TestOpenCodeGoProbe:
    probe = OpenCodeGoProbe()

    def test_the_module_exports_the_probe(self):
        assert [p.id for p in PROBES] == ["opencode_go"]

    def test_matches_the_go_lane(self):
        assert (
            self.probe.match("https://opencode.ai/zen/go/v1")
            == "https://opencode.ai/zen/go/v1/usage"
        )

    def test_reports_the_zen_lane_as_unsupported(self):
        assert self.probe.match("https://opencode.ai/zen/v1") == ""
        match = resolve_probe("https://opencode.ai/zen/v1", probes=_PROBES)
        assert match is not None and match.url is None
        assert "no keyed usage endpoint" in (match.unsupported or "")

    def test_ignores_other_vendors(self):
        assert self.probe.match("https://api.example.com/v1") is None

    def test_parses_percent_as_used(self):
        # Relative, not a fixed instant: a window whose reset time has passed
        # stops blocking, so a hardcoded date would turn this test red later.
        resets = (datetime.now(timezone.utc) + timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        plan, windows = self.probe.parse(
            {
                "usage": {
                    "rolling": {
                        "status": "ok",
                        "percent": 12,
                        "resetsAt": "2026-10-19T22:22:28.331Z",
                    },
                    "weekly": {"status": "ok", "percent": 94},
                    "monthly": {
                        "status": "rate-limited",
                        "percent": 100,
                        "resetsAt": resets,
                    },
                }
            }
        )
        assert plan is None
        assert [w.name for w in windows] == ["5 hours", "7 days", "Month"]
        assert windows[0].used_percent == 12
        assert windows[0].span_seconds == 5 * 3600
        assert windows[2].used_percent == 100
        assert windows[2].exhausted

    def test_malformed_answer_is_an_error(self):
        with pytest.raises(QuotaProbeError):
            self.probe.parse({"usage": {}})

    def test_error_wording(self):
        assert "does not authenticate" in self.probe.describe_error(401, {})
        assert "no Go subscription" in self.probe.describe_error(403, {})

    def test_inband_429_names_the_window(self):
        signal = self.probe.inband(
            429, {"error": {"message": "limit"}, "metadata": {"limitName": "weekly"}}
        )
        assert signal is not None
        assert signal.window == "weekly"
        assert signal.cooldown_seconds == 7 * 24 * 3600

    def test_inband_ignores_other_statuses(self):
        assert self.probe.inband(500, {}) is None


class TestProbeResolution:
    def test_the_go_lane_resolves_to_its_usage_endpoint(self):
        match = resolve_probe("https://opencode.ai/zen/go/v1", probes=_PROBES)
        assert match is not None
        assert match.probe.id == "opencode_go"
        assert match.url == "https://opencode.ai/zen/go/v1/usage"

    def test_explicit_probe_wins(self):
        match = resolve_probe(
            "https://proxy.example.com/v1",
            probes=_PROBES,
            probe_id="opencode_go",
            url="https://proxy.example.com/usage",
        )
        assert match is not None
        assert match.probe.id == "opencode_go"
        assert match.url == "https://proxy.example.com/usage"

    def test_unknown_probe_is_an_error(self):
        with pytest.raises(ValueError):
            resolve_probe("https://api.example.com", probes=_PROBES, probe_id="nope")
