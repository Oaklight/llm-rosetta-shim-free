"""Open Design Cloud sign-in — the shim's own credential exchange.

Open Design splits one account across two planes:

* the **model plane** (``https://amr-link.open-design.ai/v1``) serves LLM
  traffic and accepts only the runtime key (``sk-amr-…``);
* the **control plane** (``https://amr-api.open-design.ai``) serves account
  and Coding Plan reads and accepts only the control key (``vela_ctrl_…``).

The two refuse each other's credentials, and the control key is never shown in
the web UI: the only way to obtain it is the CLI device-authorization flow
implemented here.  A human opens an activation URL, approves the device, and
the next poll returns both keys at once.

Keys do not expire and the vendor issues no refresh token, so there is no
rotation: the stored record is the credential.  Because of that this module
uses the record for identity only — the runtime key is what a model request
sends, and the control key is kept beside it for the allowance reader in
``quota.py``.

The loader executes this file as a **flat module**: standard library only (plus
the core contract module the loader documents), no relative or sibling imports.

Future contract
~~~~~~~~~~~~~~~

The current :class:`llm_rosetta.contracts.auth.AuthExchange` serves one
credential to the gateway, and for this provider that is the runtime key.  A
later core revision adds ``credential_for(role)`` so a shim can serve more than
one credential; ``"control"`` will be served from this file, out of the
``control`` field of the record written below.  Nothing else about this vendor
logic should need to move.

Two rules shape the code:

* **A secret never leaves in a message.** The device secret and both keys are
  scrubbed from any vendor error text this module raises; the record is the
  only place a key is written, with mode ``0600`` and an atomic rename.
* **A 3xx is an error.** The control plane is the only host this module talks
  to; a redirect is either misconfiguration or someone else's server.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llm_rosetta.contracts.auth import (
    AuthContext,
    AuthExchangeError,
    BaseAuthExchange,
    InteractiveSetupRequired,
)

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

CONTROL_PLANE = "https://amr-api.open-design.ai"
MODEL_PLANE = "https://amr-link.open-design.ai/v1"

#: What the device flow identifies itself as.  ``cliVersion`` is the value the
#: vendor's own CLI sends for this protocol; ``profile`` selects the
#: production control plane.
CLI_VERSION = "0.1.4"
PROFILE = "prod"

#: The control plane sits behind a CDN that refuses urllib's default
#: ``Python-urllib/x.y`` agent outright (Cloudflare error 1010), so every
#: request must name a client.
USER_AGENT = f"open-design-cli/{CLI_VERSION}"

#: One key is exactly these many characters, with this prefix.  The vendor has
#: never issued anything else; anything else is a copy-paste accident or a
#: record for a different service.
RUNTIME_PREFIX = "sk-amr-"
RUNTIME_LENGTH = 39
CONTROL_PREFIX = "vela_ctrl_"
CONTROL_LENGTH = 42

#: One outbound call, and the cap on what will be read from it.  The device
#: flow answers a few hundred bytes; a body far beyond that is not an answer
#: we want in memory.
TIMEOUT = 25.0
MAX_BYTES = 1024 * 1024

#: Bounds for the vendor's ``pollIntervalSeconds``.  The floor keeps a
#: malformed answer from turning ``login()`` into a busy loop.
MIN_INTERVAL = 0.1
MAX_INTERVAL = 60.0
DEFAULT_INTERVAL = 2.0

#: Used only when the vendor omits ``expiresAt``: ten minutes is the usual
#: device-code lifetime and is short enough to be safe.
FALLBACK_TTL = 600.0

RECORD_NAME = "credential.json"
PENDING_NAME = "pending-login.json"

#: Status words after which polling can never succeed.
TERMINAL_STATUSES = frozenset(
    {"expired", "canceled", "cancelled", "denied", "rejected"}
)

#: Wall clock and sleep behind module attributes so tests can drive them.
_now = time.time
_sleep = time.sleep


# ---------------------------------------------------------------------------
# HTTP — stdlib, no redirects, capped
# ---------------------------------------------------------------------------


class _Refused(Exception):
    """A non-2xx answer, kept apart from transport failures.

    Polling maps a status code to a message ("refused" for 401, "no longer
    valid" for 404), which it cannot do if the status is only in a string.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse 3xx instead of following it.

    Following a redirect would hand the device secret to whatever host the
    answer names, so a redirect is reported as the failure it is.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise AuthExchangeError(
            f"{req.full_url} answered {code} → {newurl}; refusing to follow a redirect"
        )


_OPENER = urllib.request.build_opener(_NoRedirect)


def _scrub(text: str, secrets: tuple[str, ...]) -> str:
    """Remove secret values from vendor text before it can be raised.

    A vendor's error body is not under our control; a device secret is.  Any
    value we know to be secret is replaced, so a message is safe to show.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _vendor_message(text: str) -> str:
    """Return the vendor's own wording from an error body, if it has one."""
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except ValueError:
        return stripped[:300] or "no detail"
    if isinstance(parsed, dict):
        for key in ("error", "message", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value[:300]
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return value["message"][:300]
    return stripped[:300] or "no detail"


def _request(
    url: str,
    *,
    data: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    method: str | None = None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Call *url* and decode one JSON object from the answer.

    Raises:
        _Refused: The vendor answered a non-2xx status; carries its wording.
        AuthExchangeError: The call could not be made, redirected, or did not
            answer a JSON object.
    """
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        url, data=body, method=method or ("POST" if body is not None else "GET")
    )
    for key, value in {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        **(headers or {}),
    }.items():
        request.add_header(key, value)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = _scrub(exc.read(4096).decode("utf-8", "replace"), secrets)
        raise _Refused(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise AuthExchangeError(f"{url} unreachable: {exc.reason}") from exc
    if len(raw) > MAX_BYTES:
        raise AuthExchangeError(f"{url} answered more than {MAX_BYTES} bytes")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthExchangeError(f"{url} did not answer JSON") from exc
    if not isinstance(payload, dict):
        raise AuthExchangeError(
            f"{url} answered {type(payload).__name__}, not an object"
        )
    return payload


# ---------------------------------------------------------------------------
# Small conversions
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    """Return *value* when it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value.strip() else None


def _epoch(value: Any) -> float | None:
    """Parse the vendor's ``expiresAt`` as epoch seconds.

    The measured answer has not been pinned down between an epoch number and
    an ISO string, so both are accepted rather than one guessed at.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def _interval(value: Any) -> float:
    """Clamp the vendor's poll interval into a range a loop can honour."""
    moment = (
        value
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )
    if moment is None or moment <= 0:
        return DEFAULT_INTERVAL
    return float(min(MAX_INTERVAL, max(MIN_INTERVAL, moment)))


def _valid_runtime(value: Any) -> bool:
    """Whether *value* is a runtime key and nothing else."""
    return (
        isinstance(value, str)
        and len(value) == RUNTIME_LENGTH
        and value.startswith(RUNTIME_PREFIX)
    )


def _valid_control(value: Any) -> bool:
    """Whether *value* is a control key and nothing else."""
    return (
        isinstance(value, str)
        and len(value) == CONTROL_LENGTH
        and value.startswith(CONTROL_PREFIX)
    )


# ---------------------------------------------------------------------------
# The record store
# ---------------------------------------------------------------------------


def _slug(value: str) -> str:
    """Return a directory-safe spelling of a provider name."""
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in value) or "profile"


def _state_dir(ctx: AuthContext) -> Path:
    """Return the directory this provider's record lives in.

    The gateway supplies one per configured provider.  When it does not, the
    provider name must still be part of the path: two providers of one shim
    are two accounts.
    """
    if ctx.state_dir:
        return Path(ctx.state_dir)
    return Path.home() / ".config" / "llm-rosetta" / "opendesign" / _slug(ctx.provider)


def _record_path(ctx: AuthContext) -> Path:
    return _state_dir(ctx) / RECORD_NAME


def _pending_path(ctx: AuthContext) -> Path:
    return _state_dir(ctx) / PENDING_NAME


def _write_private(path: Path, text: str) -> None:
    """Write *text* to *path* atomically, readable only by its owner.

    The temporary file is created ``0600`` before anything is written, so the
    secret is never briefly world-readable; ``os.replace`` makes the swap
    atomic, so a reader sees either the old file or the new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_record(ctx: AuthContext) -> dict[str, Any]:
    """Return the stored record, or raise the reason there is none."""
    path = _record_path(ctx)
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError as exc:
        raise InteractiveSetupRequired(
            f"no Open Design sign-in at {path}; run the sign-in once"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthExchangeError(
            f"credential record at {path} is unreadable: {exc}"
        ) from exc
    if not isinstance(record, dict):
        raise AuthExchangeError(f"credential record at {path} is not an object")
    if not _valid_runtime(record.get("runtime")):
        raise AuthExchangeError(
            f"credential record at {path} holds no runtime key; sign in again"
        )
    return record


def _save_record(ctx: AuthContext, record: Mapping[str, Any]) -> None:
    _write_private(
        _record_path(ctx), json.dumps(dict(record), indent=2, sort_keys=True) + "\n"
    )


def _discard_record(ctx: AuthContext) -> None:
    try:
        _record_path(ctx).unlink()
    except FileNotFoundError:
        pass


def _record(control: str, runtime: str, user: Any) -> dict[str, Any]:
    """Build the stored shape from one approved poll."""
    return {
        "runtime": runtime,
        "control": control,
        "user": dict(user) if isinstance(user, Mapping) else {},
        "control_plane": CONTROL_PLANE,
        "model_plane": MODEL_PLANE,
    }


def _summary(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the token-free part of a record, for a UI to render.

    There is no ``expires_at``: Open Design's keys do not expire and the
    vendor never reports one.  Inventing a field here would make the panel
    show a countdown that means nothing.
    """
    user = record.get("user")
    profile = user if isinstance(user, Mapping) else {}
    return {
        "connected": True,
        "id": _text(profile.get("id")),
        "email": _text(profile.get("email")),
        "name": _text(profile.get("name")),
        "plan": _text(profile.get("plan")),
        "status": _text(profile.get("status")),
    }


# ---------------------------------------------------------------------------
# The pending device authorization
# ---------------------------------------------------------------------------


def _read_pending(ctx: AuthContext) -> dict[str, Any]:
    """Return the stored device authorization, refusing a stale one."""
    path = _pending_path(ctx)
    try:
        with open(path, encoding="utf-8") as handle:
            pending = json.load(handle)
    except FileNotFoundError as exc:
        raise AuthExchangeError("no sign-in is in progress; start one first") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthExchangeError("the pending sign-in is unreadable") from exc
    if not isinstance(pending, dict):
        raise AuthExchangeError("the pending sign-in has an invalid shape")
    if not _text(pending.get("device_id")) or not _text(pending.get("device_secret")):
        raise AuthExchangeError("the pending sign-in has an invalid shape")
    expires_at = pending.get("expires_at")
    if not isinstance(expires_at, (int, float)) or _now() >= float(expires_at):
        _discard_pending(ctx)
        raise AuthExchangeError("the sign-in expired; start again")
    return pending


def _discard_pending(ctx: AuthContext) -> None:
    """Consume the device authorization, including after a failure."""
    try:
        _pending_path(ctx).unlink()
    except FileNotFoundError:
        pass


def begin_login(ctx: AuthContext) -> dict[str, Any]:
    """Start a device authorization and return only what a human needs.

    Starting again supersedes an unfinished sign-in: only the newest device
    secret is stored, so two open tabs cannot both mint a record.

    Returns:
        ``authorization_url``, ``user_code``, ``expires_at`` (epoch seconds)
        and ``interval`` (seconds).  The device secret is stored, never
        returned.

    Raises:
        AuthExchangeError: The control plane refused or gave an unusable answer.
    """
    url = f"{CONTROL_PLANE}/api/v1/cli/device-authorizations"
    try:
        payload = _request(
            url,
            data={
                "cliVersion": CLI_VERSION,
                "host": platform.node() or "unknown",
                "profile": PROFILE,
            },
        )
    except _Refused as exc:
        raise AuthExchangeError(
            f"the sign-in could not start ({exc.status}): {_vendor_message(exc.detail)}"
        ) from None
    device_id = _text(payload.get("deviceId"))
    device_secret = _text(payload.get("deviceSecret"))
    user_code = _text(payload.get("userCode"))
    activation_url = _text(payload.get("activationUrl"))
    if not (device_id and device_secret and user_code and activation_url):
        raise AuthExchangeError(
            "the sign-in service did not return a device authorization"
        )
    expires_at = _epoch(payload.get("expiresAt")) or (_now() + FALLBACK_TTL)
    interval = _interval(payload.get("pollIntervalSeconds"))
    pending = {
        "device_id": device_id,
        "device_secret": device_secret,
        "user_code": user_code,
        "activation_url": activation_url,
        "expires_at": expires_at,
        "interval": interval,
        "created_at": _now(),
    }
    _write_private(
        _pending_path(ctx), json.dumps(pending, indent=2, sort_keys=True) + "\n"
    )
    return {
        "authorization_url": activation_url,
        "user_code": user_code,
        "expires_at": expires_at,
        "interval": interval,
    }


def _poll_once(ctx: AuthContext, pending: Mapping[str, Any]) -> dict[str, Any] | None:
    """Poll the device authorization once.

    Returns:
        The stored record once the device is approved, ``None`` while pending.

    Raises:
        AuthExchangeError: The poll was refused, the authorization is terminal,
            or an approved answer carried no usable keys.
    """
    device_id = str(pending["device_id"])
    device_secret = str(pending["device_secret"])
    url = (
        f"{CONTROL_PLANE}/api/v1/cli/device-authorizations/"
        f"{urllib.parse.quote(device_id, safe='')}/token"
    )
    try:
        payload = _request(
            url,
            data={"deviceSecret": device_secret},
            secrets=(device_secret,),
        )
    except _Refused as exc:
        detail = _vendor_message(exc.detail)
        if exc.status == 401:
            # The device secret itself was refused; no retry with this one can
            # succeed, so a stale record must not keep the next attempt alive.
            _discard_pending(ctx)
            raise AuthExchangeError(f"the sign-in was refused: {detail}") from None
        if exc.status == 404:
            _discard_pending(ctx)
            raise AuthExchangeError(
                "the sign-in is no longer valid; start again"
            ) from None
        raise AuthExchangeError(
            f"the sign-in poll failed ({exc.status}): {detail}"
        ) from None

    status = (_text(payload.get("status")) or "").lower()
    control = payload.get("controlKey")
    runtime = payload.get("runtimeKey")
    if control is not None or runtime is not None:
        if not (_valid_control(control) and _valid_runtime(runtime)):
            raise AuthExchangeError(
                "the sign-in was approved but the answer carried no usable credentials"
            )
        record = _record(str(control), str(runtime), payload.get("user"))
        _save_record(ctx, record)
        _discard_pending(ctx)
        return record
    if status in TERMINAL_STATUSES:
        _discard_pending(ctx)
        raise AuthExchangeError(f"the sign-in {status}; start again")
    if status == "approved":
        raise AuthExchangeError(
            "the sign-in was approved but the answer carried no usable credentials"
        )
    return None


def complete_login(ctx: AuthContext, callback_url: str) -> dict[str, Any]:
    """Poll once for the device approval started by :func:`begin_login`.

    The device flow has no browser callback, so *callback_url* is accepted
    only for contract shape: the admin panel submits the activation URL it
    showed the operator, or an empty string.  Its content is not used — the
    device secret on disk is the whole proof of this sign-in.

    Raises:
        AuthExchangeError: Not approved yet (the panel retries), refused,
            terminal, or expired.
    """
    if not isinstance(callback_url, str):
        raise AuthExchangeError("the sign-in has no callback URL to submit")
    pending = _read_pending(ctx)
    record = _poll_once(ctx, pending)
    if record is None:
        raise AuthExchangeError("the sign-in is not approved yet")
    return _summary(record)


def login(ctx: AuthContext) -> dict[str, Any]:
    """Run the device sign-in here, where the operator is.

    Starts the flow, then polls at the vendor's interval until the device is
    approved or the authorization expires.  Blocking by design: the operator
    is watching, and this is the CLI path, not the gateway's.

    Returns:
        The stored record.  It is the credential; the caller must not log it.

    Raises:
        AuthExchangeError: The sign-in failed, was refused, or timed out.
    """
    started = begin_login(ctx)
    # The CLI prints nothing until login() returns, and this flow has no
    # browser callback: the operator can only approve the device if the URL
    # and code are shown now.
    print(
        "Open Design sign-in: open "
        f"{started['authorization_url']} and approve the device "
        f"(code {started['user_code']}).",
        flush=True,
    )
    pending = _read_pending(ctx)
    deadline = float(pending["expires_at"])
    interval = float(pending["interval"])
    while _now() < deadline:
        record = _poll_once(ctx, pending)
        if record is not None:
            return record
        _sleep(min(interval, max(0.0, deadline - _now())))
    _discard_pending(ctx)
    raise AuthExchangeError("the sign-in expired; start again")


#: The role the allowance reader names.  ``"control"`` is this vendor's word
#: for the key the control plane accepts; ``quota.py`` declares the same
#: string, because two flat modules cannot share one constant.
CONTROL_ROLE = "control"


def _credential(ctx: AuthContext) -> str:
    """Return the stored runtime key.

    There is no refresh: the vendor issues no refresh token and the keys do
    not expire, so a stored key is either usable or the sign-in must happen
    again.
    """
    return str(_read_record(ctx)["runtime"])


def _control(ctx: AuthContext) -> str:
    """Return the stored control key, the one the control plane accepts.

    A record written before the control key was kept, or one installed from a
    partial paste, says so rather than sending the runtime key to a plane
    that answers it with 401.
    """
    record = _read_record(ctx)
    control = record.get("control")
    if not _valid_control(control):
        raise AuthExchangeError(
            "the credential record holds no control key; sign in again"
        )
    return str(control)


class OpenDesignSignIn(BaseAuthExchange):
    """The control plane's device-authorization exchange, as the gateway sees it."""

    kind = "device"
    consumes_key = False

    def needs_interactive_setup(self, ctx: AuthContext) -> bool:
        """Whether a human still has to approve a device for this provider."""
        return not _record_path(ctx).exists()

    async def credential(self, ctx: AuthContext) -> str:
        """Return the runtime key the model plane accepts."""
        return _credential(ctx)

    async def credential_for(self, ctx: AuthContext, role: str) -> str:
        """Return the credential *role* names.

        The allowance reader asks for ``"control"``; every other role is the
        model credential, which is also what a caller that names none gets.
        """
        if role == CONTROL_ROLE:
            return _control(ctx)
        return await self.credential(ctx)

    def account_id(self, ctx: AuthContext) -> str | None:
        """Return the account email, or its id when no email was issued.

        The runtime key is the credential and rotates on a new sign-in; the
        account does not, so neither the email nor the id is the token.
        """
        try:
            record = _read_record(ctx)
        except (InteractiveSetupRequired, AuthExchangeError):
            return None
        user = record.get("user")
        profile = user if isinstance(user, Mapping) else {}
        return _text(profile.get("email")) or _text(profile.get("id"))

    def describe(self, ctx: AuthContext) -> dict[str, Any] | None:
        """Return who is signed in; these keys have no expiry to show."""
        try:
            record = _read_record(ctx)
        except (InteractiveSetupRequired, AuthExchangeError):
            return None
        return _summary(record)

    def begin_login(self, ctx: AuthContext) -> dict[str, Any]:
        """Start a device authorization for the admin panel to show."""
        return begin_login(ctx)

    def complete_login(self, ctx: AuthContext, callback_url: str) -> dict[str, Any]:
        """Poll once for the approval the operator gave in a browser."""
        return complete_login(ctx, callback_url)

    def login(self, ctx: AuthContext) -> dict[str, Any]:
        """Run the device flow here, at the CLI."""
        return login(ctx)

    def install(self, ctx: AuthContext, record: Any) -> dict[str, Any]:
        """Adopt a record produced on a machine that ran the sign-in.

        Both keys are validated by prefix and length before anything is
        stored; a record for another service, a truncated paste, or a raw
        vendor payload (``runtimeKey``/``controlKey``) is refused rather than
        saved in a shape the rest of this module would not read.
        """
        if not isinstance(record, Mapping):
            raise AuthExchangeError("the credential record is not an object")
        runtime = record.get("runtime")
        control = record.get("control")
        if not _valid_runtime(runtime):
            raise AuthExchangeError(
                "the credential record carries no runtime key "
                f"({RUNTIME_PREFIX}…, {RUNTIME_LENGTH} characters)"
            )
        if not _valid_control(control):
            raise AuthExchangeError(
                "the credential record carries no control key "
                f"({CONTROL_PREFIX}…, {CONTROL_LENGTH} characters)"
            )
        user = record.get("user")
        control_plane = _text(record.get("control_plane")) or CONTROL_PLANE
        model_plane = _text(record.get("model_plane")) or MODEL_PLANE
        stored = {
            "runtime": runtime,
            "control": control,
            "user": dict(user) if isinstance(user, Mapping) else {},
            "control_plane": control_plane,
            "model_plane": model_plane,
        }
        _save_record(ctx, stored)
        return _summary(stored)

    def revoke(self, ctx: AuthContext) -> bool:
        """Forget the record.  Returns ``False``: nothing was revoked upstream.

        The vendor documents no revocation endpoint for these keys, so the
        record is removed — even if forgetting it is all that happens — and
        the keys stay live until Open Design rotates them.  Returning ``True``
        would claim a revocation that never happened.
        """
        _discard_record(ctx)
        return False


EXCHANGE = OpenDesignSignIn()
