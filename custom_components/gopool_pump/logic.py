"""Pure, framework-independent logic for the GoPool Variable Speed Pump
integration.

Deliberately free of any `homeassistant.*` import so it can be unit-tested
with plain pytest — no `pytest-homeassistant-custom-component` harness, no
running Home Assistant core, no network, nothing beyond this repo's own
runtime dependencies (see manifest.json). See tests/test_logic.py.

`tinytuya` IS imported here (for its ERR_KEY_OR_VER error code constant) —
that's fine for this goal: it's a lightweight, pure-Python runtime
dependency of this integration already, not `homeassistant` itself, and
importing it doesn't pull in HA or anything heavy.

Anything that ends up here should be reducible to "given these plain
values (dicts, numbers, strings), return this plain value" — no
coordinator, no config entry, no `hass` access, no I/O. Code that
genuinely needs those stays in __init__.py / config_flow.py / sensor.py
and calls into here for the branchy/interesting part.
"""

from __future__ import annotations

import tinytuya


def interpolate_rpm_to_watts(rpm: float, table: list[tuple[int, int]]) -> float:
    """Piecewise-linear interpolation over an ascending (rpm, watts) table.

    Clamped at both ends (a commanded RPM outside the calibrated range —
    shouldn't normally happen given the number/select entities' own
    min/max, but a stale/out-of-range DP value is possible — reports the
    nearest known endpoint rather than extrapolating).

    Moved here unchanged from sensor.py's former `_interpolate()` so it
    can be tested against the real RPM_POWER_TABLES data (see const.py)
    without importing Home Assistant.
    """
    if rpm <= table[0][0]:
        return float(table[0][1])
    if rpm >= table[-1][0]:
        return float(table[-1][1])
    for (r1, w1), (r2, w2) in zip(table, table[1:]):
        if r1 <= rpm <= r2:
            ratio = (rpm - r1) / (r2 - r1)
            return w1 + ratio * (w2 - w1)
    return float(table[-1][1])  # pragma: no cover - unreachable, table covers the range


def is_valid_status_result(result: dict | None) -> bool:
    """True only for a genuinely usable tinytuya status() response.

    tinytuya doesn't only fail by returning a falsy value or omitting
    "dps" entirely — a busy/contended socket can come back as something
    like {"Error": "...", "Err": "905", "dps": {}}: a dict, with a "dps"
    key, that's still not usable data. Accepting that as "successful"
    would overwrite the coordinator's last known good state with an
    empty dict — see GoPoolCoordinator._async_update_data in __init__.py
    for the caller-side history of why this check exists.
    """
    return bool(result) and bool(result.get("dps")) and not result.get("Error")


def is_key_error_result(result: dict | None) -> bool:
    """True when a tinytuya status() call failed specifically because the
    stored local_key (or protocol version — fixed at 3.5 for this pump
    line, so in practice this always means the key) was rejected during
    the session-key handshake.

    tinytuya surfaces this as {"Error": "Check device key or version",
    "Err": "914", "Payload": None} — "914" being ERR_KEY_OR_VER in
    tinytuya's own core/error_helper.py, returned by XenonDevice
    whenever `_negotiate_session_key()` fails for protocol >= 3.4 (this
    pump line is fixed at 3.5, see DEFAULT_PROTOCOL_VERSION in const.py),
    i.e. the handshake step that actually exercises local_key — a plain
    TCP-level problem (device offline, wrong IP, firewalled) fails
    earlier/differently (ERR_OFFLINE/ERR_CONNECT/ERR_TIMEOUT) and is
    NOT what this function is for.

    Distinguishing this from every other failure mode matters because
    it's the one case where retrying (the existing close+reconnect,
    then "keep last known state" logic in _async_update_data) will never
    self-correct — the key genuinely changed, most commonly because the
    pump was removed and re-added in the Smart Life app. See
    GoPoolCoordinator._async_update_data (__init__.py), which raises
    ConfigEntryAuthFailed on this to trigger Home Assistant's reauth
    flow (async_step_reauth in config_flow.py) instead of retrying
    forever or silently going stale.
    """
    # getattr(..., 914) rather than a bare tinytuya.ERR_KEY_OR_VER: this
    # project's manifest.json only floors tinytuya at >=1.13.0 (no upper
    # bound), and while ERR_KEY_OR_VER has been present in every version
    # checked so far, falling back to the literal protocol-level error
    # code is cheap insurance against a hypothetical older/renamed
    # install ever raising AttributeError out of a poll cycle instead of
    # just failing this one (correct) classification check.
    key_err_code = getattr(tinytuya, "ERR_KEY_OR_VER", 914)
    return bool(result) and result.get("Err") == str(key_err_code)


def pick_reauth_default_device(
    devices: dict[str, dict], reauth_device_id: str | None
) -> str | None:
    """Which device_id the "pick_device" step's selector should default to.

    Reauth (see config_flow.py's async_step_reauth): the account's device
    list is re-fetched from scratch (the local_key rotated, but the
    account's device_id set for a given physical pump is expected to stay
    the same — see this project's README on what actually rotates when a
    pump is removed/re-added in Smart Life). If the entry being
    reauthenticated's device_id still shows up in that list, pre-select
    exactly it — no reason to make the user re-pick a device they already
    configured. If it's gone (an edge case: e.g. the pump really was
    fully deleted and re-paired as a new device_id, not just rotated),
    fall back to the same "first device" default a fresh setup uses,
    letting the user pick manually instead of guessing wrong.

    Plain setup (reauth_device_id=None) always falls through to that same
    "first device" default — unchanged behavior from before this existed.
    """
    if reauth_device_id is not None and reauth_device_id in devices:
        return reauth_device_id
    return next(iter(devices), None)


def should_attempt_ip_rescan(
    *,
    has_ever_succeeded: bool,
    consecutive_offline_failures: int,
    seconds_since_last_rescan_attempt: float | None,
    after_failures: int,
    cooldown_seconds: float,
) -> bool:
    """Whether GoPoolCoordinator._maybe_heal_ip (__init__.py) should run a
    LAN rescan right now, looking for the pump at a new IP after its
    stored one stopped responding.

    Two different policies, because the two situations behave
    differently:

    - has_ever_succeeded=False: this entry has never completed a
      successful poll yet (a fresh setup mid-retry, or a reload/restart
      where connectivity is already broken from the very first attempt).
      There's no run of consecutive cycles to threshold against here —
      each failed setup attempt gets a brand new GoPoolCoordinator (and
      so a fresh consecutive_offline_failures back at 0) — so this scans
      on every failed attempt instead. That's intentionally more eager
      than the steady-state policy below; Home Assistant's own
      ConfigEntryNotReady retry backoff (spacing out setup attempts
      itself) is what keeps this from hammering anything.
    - has_ever_succeeded=True: this entry WAS working. Scan only after
      `after_failures` consecutive failed poll cycles — a brief network
      blip must not trigger one — and no more than once per
      `cooldown_seconds` after that, so an extended outage (pump powered
      off, real network down) doesn't re-scan on every single cycle
      forever.
    """
    if not has_ever_succeeded:
        return True
    if consecutive_offline_failures < after_failures:
        return False
    if (
        seconds_since_last_rescan_attempt is not None
        and seconds_since_last_rescan_attempt < cooldown_seconds
    ):
        return False
    return True
