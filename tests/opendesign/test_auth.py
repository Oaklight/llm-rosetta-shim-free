"""The device-authorization exchange, exercised through the real loader."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llm_rosetta.contracts.auth import (
    AuthContext,
    AuthExchangeError,
    InteractiveSetupRequired,
)

_ROOT = Path(__file__).resolve().parents[2]
_AUTH = (
    _ROOT / "src" / "llm_rosetta_shim_contrib" / "providers" / "opendesign" / "auth.py"
)

_RUNTIME = "sk-amr-" + "r" * 32
_CONTROL = "vela_ctrl_" + "c" * 32
_DEVICE_SECRET = "device-secret-that-must-not-escape"


def _iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class Clock:
    """A fake wall clock and sleep, so polling runs without waiting."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.moment = start

    def __call__(self) -> float:
        return self.moment

    def sleep(self, seconds: float) -> None:
        self.moment += seconds


class Transport:
    """Stand-in for ``auth._request``: records calls, replays answers."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def __call__(self, url, *, data=None, headers=None, method=None, secrets=()):
        self.calls.append(
            {"url": url, "data": data, "headers": headers, "secrets": secrets}
        )
        if not self.answers:
            raise AssertionError(f"unexpected request to {url}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


# The module is loaded by path, the way the shim loader executes it: flat,
# never through the plugin package (whose entry point would re-enter here).
_spec = importlib.util.spec_from_file_location("opendesign_auth_under_test", _AUTH)
assert _spec is not None and _spec.loader is not None
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)


@pytest.fixture(name="auth")
def auth_fixture():
    """The already-executed exchange module."""
    return auth


@pytest.fixture()
def ctx(tmp_path):
    return AuthContext(provider="opendesign", state_dir=str(tmp_path / "state"))


@pytest.fixture()
def pending_start():
    return {
        "deviceId": "device-1",
        "deviceSecret": _DEVICE_SECRET,
        "userCode": "ABCD-1234",
        "activationUrl": "https://open-design.ai/activate?code=ABCD-1234",
        "expiresAt": _iso(1_000_600.0),
        "pollIntervalSeconds": 2,
        "status": "pending",
    }


@pytest.fixture()
def approved():
    return {
        "controlKey": _CONTROL,
        "runtimeKey": _RUNTIME,
        "user": {
            "id": "user-1",
            "email": "operator@example.test",
            "name": "Operator",
            "plan": "go",
            "status": "active",
        },
    }


def _record_path(ctx: AuthContext) -> Path:
    return Path(ctx.state_dir) / "credential.json"


def _pending_path(ctx: AuthContext) -> Path:
    return Path(ctx.state_dir) / "pending-login.json"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# begin_login
# ---------------------------------------------------------------------------


def test_begin_login_persists_the_device_secret_but_never_returns_it(
    auth, ctx, pending_start, monkeypatch
):
    transport = Transport(pending_start)
    monkeypatch.setattr(auth, "_request", transport)

    result = auth.begin_login(ctx)

    assert result == {
        "authorization_url": "https://open-design.ai/activate?code=ABCD-1234",
        "user_code": "ABCD-1234",
        "expires_at": 1_000_600.0,
        "interval": 2.0,
    }
    assert _DEVICE_SECRET not in json.dumps(result)
    pending = json.loads(_pending_path(ctx).read_text(encoding="utf-8"))
    assert pending["device_secret"] == _DEVICE_SECRET
    assert _mode(_pending_path(ctx)) == 0o600

    call = transport.calls[0]
    assert call["url"] == (
        "https://amr-api.open-design.ai/api/v1/cli/device-authorizations"
    )
    assert call["data"] == {
        "cliVersion": "0.1.4",
        "host": auth.platform.node() or "unknown",
        "profile": "prod",
    }


def test_begin_login_refuses_an_answer_without_a_device(auth, ctx, monkeypatch):
    monkeypatch.setattr(auth, "_request", Transport({"status": "pending"}))
    with pytest.raises(AuthExchangeError, match="device authorization"):
        auth.begin_login(ctx)


def test_begin_login_reports_a_refused_start(auth, ctx, monkeypatch):
    monkeypatch.setattr(
        auth, "_request", Transport(auth._Refused(500, '{"error":"boom"}'))
    )
    with pytest.raises(AuthExchangeError, match="could not start.*boom"):
        auth.begin_login(ctx)


# ---------------------------------------------------------------------------
# complete_login: pending, approved, terminal
# ---------------------------------------------------------------------------


def _started(auth, ctx, monkeypatch, *answers, start):
    clock = Clock(1_000_000.0)
    monkeypatch.setattr(auth, "_now", clock)
    monkeypatch.setattr(auth, "_request", Transport(start, *answers))
    auth.begin_login(ctx)


def test_complete_login_says_so_while_the_device_is_pending(
    auth, ctx, pending_start, monkeypatch
):
    _started(auth, ctx, monkeypatch, {"status": "pending"}, start=pending_start)
    with pytest.raises(AuthExchangeError, match="not approved yet"):
        auth.complete_login(ctx, "")
    assert _record_path(ctx).exists() is False


def test_complete_login_stores_the_record_when_approved(
    auth, ctx, pending_start, approved, monkeypatch
):
    _started(auth, ctx, monkeypatch, approved, start=pending_start)

    summary = auth.complete_login(ctx, "")

    assert summary == {
        "connected": True,
        "id": "user-1",
        "email": "operator@example.test",
        "name": "Operator",
        "plan": "go",
        "status": "active",
    }
    assert _RUNTIME not in json.dumps(summary)
    assert _CONTROL not in json.dumps(summary)
    record = json.loads(_record_path(ctx).read_text(encoding="utf-8"))
    assert record["runtime"] == _RUNTIME
    assert record["control"] == _CONTROL
    assert record["control_plane"] == "https://amr-api.open-design.ai"
    assert record["model_plane"] == "https://amr-link.open-design.ai/v1"
    assert _mode(_record_path(ctx)) == 0o600
    assert not _pending_path(ctx).exists()


def test_complete_login_accepts_the_activation_url_as_its_argument(
    auth, ctx, pending_start, approved, monkeypatch
):
    _started(auth, ctx, monkeypatch, approved, start=pending_start)
    summary = auth.complete_login(ctx, pending_start["activationUrl"])
    assert summary["connected"] is True


def test_a_refused_poll_carries_vendor_wording_and_no_secret(
    auth, ctx, pending_start, monkeypatch
):
    _started(
        auth,
        ctx,
        monkeypatch,
        auth._Refused(401, '{"error":"invalid_device_secret"}'),
        start=pending_start,
    )
    with pytest.raises(AuthExchangeError) as caught:
        auth.complete_login(ctx, "")
    message = str(caught.value)
    assert "invalid_device_secret" in message
    assert _DEVICE_SECRET not in message
    assert not _pending_path(ctx).exists()


def test_a_missing_device_is_reported_as_no_longer_valid(
    auth, ctx, pending_start, monkeypatch
):
    _started(
        auth,
        ctx,
        monkeypatch,
        auth._Refused(404, '{"error":"not_found"}'),
        start=pending_start,
    )
    with pytest.raises(AuthExchangeError, match="no longer valid"):
        auth.complete_login(ctx, "")
    assert not _pending_path(ctx).exists()


@pytest.mark.parametrize(
    "status", ["expired", "canceled", "cancelled", "denied", "rejected"]
)
def test_a_terminal_status_stops_the_sign_in(
    auth, ctx, pending_start, monkeypatch, status
):
    _started(auth, ctx, monkeypatch, {"status": status}, start=pending_start)
    with pytest.raises(AuthExchangeError, match=status):
        auth.complete_login(ctx, "")
    assert not _pending_path(ctx).exists()


def test_an_approved_answer_without_keys_is_refused(
    auth, ctx, pending_start, monkeypatch
):
    _started(auth, ctx, monkeypatch, {"status": "approved"}, start=pending_start)
    with pytest.raises(AuthExchangeError, match="no usable credentials"):
        auth.complete_login(ctx, "")


def test_an_unusable_key_pair_is_refused(auth, ctx, pending_start, monkeypatch):
    _started(
        auth,
        ctx,
        monkeypatch,
        {"controlKey": _CONTROL, "runtimeKey": "sk-amr-short"},
        start=pending_start,
    )
    with pytest.raises(AuthExchangeError, match="no usable credentials"):
        auth.complete_login(ctx, "")


def test_an_expired_pending_record_is_refused(auth, ctx, pending_start, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(auth, "_now", clock)
    monkeypatch.setattr(auth, "_request", Transport(pending_start))
    auth.begin_login(ctx)
    clock.moment = 1_000_600.0  # exactly at expiry
    with pytest.raises(AuthExchangeError, match="expired"):
        auth.complete_login(ctx, "")
    assert not _pending_path(ctx).exists()


# ---------------------------------------------------------------------------
# login: the CLI loop
# ---------------------------------------------------------------------------


def test_login_polls_until_approved(auth, ctx, pending_start, approved, monkeypatch):
    clock = Clock(1_000_000.0)
    monkeypatch.setattr(auth, "_now", clock)
    monkeypatch.setattr(auth, "_sleep", clock.sleep)
    transport = Transport(pending_start, {"status": "pending"}, approved)
    monkeypatch.setattr(auth, "_request", transport)

    record = auth.login(ctx)

    assert record["runtime"] == _RUNTIME
    assert record["control"] == _CONTROL
    assert len(transport.calls) == 3  # start + two polls
    assert clock.moment == 1_000_002.0


def test_login_stops_at_the_sign_in_expiry(auth, ctx, monkeypatch):
    clock = Clock(1_000_000.0)
    monkeypatch.setattr(auth, "_now", clock)
    monkeypatch.setattr(auth, "_sleep", clock.sleep)
    start = {
        "deviceId": "device-1",
        "deviceSecret": _DEVICE_SECRET,
        "userCode": "ABCD-1234",
        "activationUrl": "https://open-design.ai/activate?code=ABCD-1234",
        "expiresAt": _iso(1_000_005.0),
        "pollIntervalSeconds": 2,
    }
    transport = Transport(start, *[{"status": "pending"}] * 10)
    monkeypatch.setattr(auth, "_request", transport)

    with pytest.raises(AuthExchangeError, match="expired"):
        auth.login(ctx)
    assert clock.moment == 1_000_005.0
    assert not _pending_path(ctx).exists()


# ---------------------------------------------------------------------------
# credential, describe, account_id, install, revoke
# ---------------------------------------------------------------------------


def test_credential_requires_a_sign_in(auth, ctx):
    assert auth.EXCHANGE.needs_interactive_setup(ctx) is True
    with pytest.raises(InteractiveSetupRequired):
        asyncio.run(auth.EXCHANGE.credential(ctx))


def test_credential_returns_the_runtime_key(auth, ctx):
    summary = auth.EXCHANGE.install(ctx, {"runtime": _RUNTIME, "control": _CONTROL})
    assert summary["connected"] is True
    assert auth.EXCHANGE.needs_interactive_setup(ctx) is False
    assert asyncio.run(auth.EXCHANGE.credential(ctx)) == _RUNTIME


def test_describe_shows_who_is_signed_in_and_no_expiry(auth, ctx):
    auth.EXCHANGE.install(
        ctx,
        {
            "runtime": _RUNTIME,
            "control": _CONTROL,
            "user": {"id": "user-1", "email": "operator@example.test", "plan": "go"},
        },
    )
    summary = auth.EXCHANGE.describe(ctx)
    assert summary["email"] == "operator@example.test"
    assert "expires_at" not in summary
    assert _RUNTIME not in json.dumps(summary)


def test_describe_is_none_without_a_record(auth, ctx):
    assert auth.EXCHANGE.describe(ctx) is None


def test_account_id_prefers_email_then_id(auth, ctx):
    auth.EXCHANGE.install(
        ctx,
        {"runtime": _RUNTIME, "control": _CONTROL, "user": {"id": "user-1"}},
    )
    assert auth.EXCHANGE.account_id(ctx) == "user-1"
    auth.EXCHANGE.install(
        ctx,
        {
            "runtime": _RUNTIME,
            "control": _CONTROL,
            "user": {"id": "user-1", "email": "operator@example.test"},
        },
    )
    assert auth.EXCHANGE.account_id(ctx) == "operator@example.test"


def test_account_id_is_none_without_a_record(auth, ctx):
    assert auth.EXCHANGE.account_id(ctx) is None


@pytest.mark.parametrize(
    "record, message",
    [
        ("not-an-object", "not an object"),
        ({"control": _CONTROL}, "runtime key"),
        ({"runtime": "sk-amr-short", "control": _CONTROL}, "runtime key"),
        ({"runtime": _RUNTIME, "control": "vela_ctrl_short"}, "control key"),
        ({"runtime": _RUNTIME}, "control key"),
        ({"runtimeKey": _RUNTIME, "controlKey": _CONTROL}, "runtime key"),
    ],
)
def test_install_refuses_anything_but_a_complete_record(auth, ctx, record, message):
    with pytest.raises(AuthExchangeError, match=message):
        auth.EXCHANGE.install(ctx, record)
    assert not _record_path(ctx).exists()


def test_revoke_forgets_the_record_and_claims_no_upstream_revocation(auth, ctx):
    auth.EXCHANGE.install(ctx, {"runtime": _RUNTIME, "control": _CONTROL})
    assert auth.EXCHANGE.revoke(ctx) is False
    assert not _record_path(ctx).exists()
    assert auth.EXCHANGE.needs_interactive_setup(ctx) is True


def test_revoke_without_a_record_is_still_false(auth, ctx):
    assert auth.EXCHANGE.revoke(ctx) is False


# ---------------------------------------------------------------------------
# Error text and the module's declared shape
# ---------------------------------------------------------------------------


def test_scrub_removes_a_known_secret(auth):
    assert auth._scrub(f"x {_DEVICE_SECRET} y", (_DEVICE_SECRET,)) == "x *** y"


def test_the_exchange_is_a_device_flow_that_owns_no_input_key(auth):
    exchange = auth.EXCHANGE
    assert exchange.kind == "device"
    assert exchange.consumes_key is False
    for capability in (
        "can_install",
        "can_login",
        "can_begin_login",
        "can_complete_login",
        "can_revoke",
    ):
        assert getattr(exchange, capability)() is True, capability


# ---------------------------------------------------------------------------
# The second credential
# ---------------------------------------------------------------------------


def test_the_control_role_returns_the_control_key(auth, ctx):
    """The allowance reader asks for "control"; the model asks for nothing."""
    auth.EXCHANGE.install(ctx, {"runtime": _RUNTIME, "control": _CONTROL, "user": {}})

    exchange = auth.EXCHANGE

    assert asyncio.run(exchange.credential_for(ctx, "control")) == _CONTROL
    assert asyncio.run(exchange.credential_for(ctx, "api_key")) == _RUNTIME
    assert asyncio.run(exchange.credential_for(ctx, "")) == _RUNTIME


def test_a_record_without_a_control_key_is_refused_for_that_role(auth, ctx):
    """Sending the runtime key to the control plane is the 401 this avoids."""
    record = {
        "runtime": _RUNTIME,
        "user": {"email": "operator@example.test"},
    }
    _record_path(ctx).parent.mkdir(parents=True, exist_ok=True)
    _record_path(ctx).write_text(json.dumps(record))

    with pytest.raises(AuthExchangeError, match="no control key"):
        asyncio.run(auth.EXCHANGE.credential_for(ctx, "control"))

    # The model credential is unaffected: it is present and valid.
    assert asyncio.run(auth.EXCHANGE.credential_for(ctx, "api_key")) == _RUNTIME
