"""The ``openai_codex`` allowance probe and its resolution against the shim.

Ported from llm-rosetta tests/gateway/test_quota.py (#1660 S7): the
``TestOpenAICodexProbe`` class, the ``openai_codex`` cases of
``TestProbeResolution``, and the plan shim's in-band declaration.
"""

from __future__ import annotations

import base64
import json

import pytest

from llm_rosetta.api import get_shim
from llm_rosetta.contracts.quota import resolve_probe
from llm_rosetta_shim_contrib.providers.openai_chatgpt.quota import OpenAICodexProbe

# The probe ships with the shim; a test resolves against it directly.
_PROBES = (OpenAICodexProbe(),)


class TestOpenAICodexProbe:
    probe = OpenAICodexProbe()

    @staticmethod
    def _token(account_id: str) -> str:
        claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
        return f"header.{payload.rstrip('=')}.signature"

    def test_reads_the_account_id_from_the_token(self):
        headers = self.probe.headers(self._token("acct-1"))
        assert headers == {"chatgpt-account-id": "acct-1"}

    def test_missing_claim_yields_no_header(self):
        assert self.probe.headers("not-a-jwt") == {}

    def test_matches_the_codex_backend(self):
        assert (
            self.probe.match("https://chatgpt.com/backend-api/codex")
            == "https://chatgpt.com/backend-api/wham/usage"
        )

    def test_parses_windows(self):
        plan, windows = self.probe.parse(
            {
                "plan_type": "plus",
                "rate_limit": {
                    "allowed": True,
                    "primary_window": {
                        "used_percent": 37,
                        "limit_window_seconds": 18000,
                        "reset_after_seconds": 600,
                    },
                    "secondary_window": {
                        "used_percent": 80,
                        "limit_window_seconds": 604800,
                        "reset_at": 1791072000,
                    },
                },
            }
        )
        assert plan == "plus"
        assert [w.name for w in windows] == ["5 hours", "7 days"]
        assert windows[0].used_percent == 37
        assert windows[1].resets_at is not None

    def test_allowed_false_blocks_even_below_100(self):
        _, windows = self.probe.parse(
            {
                "rate_limit": {
                    "allowed": False,
                    "primary_window": {
                        "used_percent": 96,
                        "limit_window_seconds": 18000,
                    },
                }
            }
        )
        assert windows[0].exhausted

    def test_credits_keep_the_account_usable(self):
        _, windows = self.probe.parse(
            {
                "credits": {"has_credits": True, "unlimited": False, "balance": "12"},
                "rate_limit": {
                    "allowed": False,
                    "primary_window": {
                        "used_percent": 100,
                        "limit_window_seconds": 18000,
                    },
                },
            }
        )
        assert not windows[0].exhausted


class TestProbeResolution:
    def test_explicit_probe_wins(self):
        match = resolve_probe(
            "https://proxy.example.com/v1",
            probes=_PROBES,
            probe_id="openai_codex",
            url="https://proxy.example.com/usage",
        )
        assert match is not None
        assert match.probe.id == "openai_codex"
        assert match.url == "https://proxy.example.com/usage"

    def test_explicit_codex_probe_falls_back_to_its_endpoint(self):
        match = resolve_probe(
            "https://api.openai.com/v1", probes=_PROBES, probe_id="openai_codex"
        )
        assert match is not None
        assert match.url == "https://chatgpt.com/backend-api/wham/usage"

    def test_unknown_probe_is_an_error(self):
        with pytest.raises(ValueError):
            resolve_probe("https://api.example.com", probes=_PROBES, probe_id="nope")

    def test_the_plan_shim_attaches_its_probe_in_band(self, register):
        register("openai_chatgpt")
        shim = get_shim("openai_chatgpt--open_responses")

        assert shim is not None
        assert shim.quota is not None
        assert shim.quota.probe == "openai_codex"
        assert shim.quota.in_band is True
        assert [p.id for p in shim.quota_probes] == ["openai_codex"]

        match = resolve_probe(
            shim.connection.base_url,
            probes=shim.quota_probes,
            probe_id="openai_codex",
            in_band=True,
        )
        assert match is not None
        assert match.probe.id == "openai_codex"
        assert match.url is None
