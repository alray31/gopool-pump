"""Unit tests for custom_components/gopool_pump/logic.py.

Deliberately the ONE test file in this project that runs with plain
pytest — no `pytest-homeassistant-custom-component`, no Home Assistant
install, no network. That's only possible because logic.py itself imports
nothing but tinytuya (see its module docstring) — every test here is
exercising real project code, not a reimplementation of it.

Run with:  pytest tests/test_logic.py -v
(or just `pytest tests/` — the other test files need the HA test harness
and are skipped/fail-fast without it; see tests/test_reauth.py's header.)
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

# A plain `from custom_components.gopool_pump.const import ...` would import
# the *package* first, i.e. run custom_components/gopool_pump/__init__.py —
# which imports `homeassistant`, exactly what this test file exists to
# avoid needing. const.py and logic.py have no relative imports of their
# own (see logic.py's module docstring), so they can be loaded directly by
# file path instead, entirely bypassing __init__.py and the package import
# machinery.
_PKG_DIR = Path(__file__).parent.parent / "custom_components" / "gopool_pump"


def _load_standalone(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, _PKG_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


const = _load_standalone("gopool_pump_const_standalone", "const.py")
logic = _load_standalone("gopool_pump_logic_standalone", "logic.py")

RPM_POWER_TABLES = const.RPM_POWER_TABLES
interpolate_rpm_to_watts = logic.interpolate_rpm_to_watts
is_key_error_result = logic.is_key_error_result
is_valid_status_result = logic.is_valid_status_result
pick_reauth_default_device = logic.pick_reauth_default_device
should_attempt_ip_rescan = logic.should_attempt_ip_rescan

# ---------------------------------------------------------------------------
# interpolate_rpm_to_watts
# ---------------------------------------------------------------------------

SIMPLE_TABLE = [(1000, 100), (2000, 200), (3000, 500)]


def test_interpolate_exact_points_return_exact_values():
    for rpm, watts in SIMPLE_TABLE:
        assert interpolate_rpm_to_watts(rpm, SIMPLE_TABLE) == watts


def test_interpolate_midpoint_is_linear():
    # Halfway between (1000, 100) and (2000, 200) -> 150.
    assert interpolate_rpm_to_watts(1500, SIMPLE_TABLE) == 150.0


def test_interpolate_uneven_segment_ratio():
    # Halfway between (2000, 200) and (3000, 500) -> 200 + 0.5*(500-200) = 350.
    assert interpolate_rpm_to_watts(2500, SIMPLE_TABLE) == 350.0


def test_interpolate_below_range_clamps_to_first():
    assert interpolate_rpm_to_watts(0, SIMPLE_TABLE) == 100.0
    assert interpolate_rpm_to_watts(999, SIMPLE_TABLE) == 100.0


def test_interpolate_above_range_clamps_to_last():
    assert interpolate_rpm_to_watts(3450, SIMPLE_TABLE) == 500.0
    assert interpolate_rpm_to_watts(999999, SIMPLE_TABLE) == 500.0


def test_interpolate_against_real_ag1_curve():
    # Guards the actual shipped calibration data (const.py), not just
    # synthetic tables — a future edit to RPM_POWER_TABLES["AG1"] that
    # breaks monotonicity or the endpoints would fail here.
    table = RPM_POWER_TABLES["AG1"]
    assert table is not None
    # Every measured point interpolates back to itself exactly.
    for rpm, watts in table:
        assert interpolate_rpm_to_watts(rpm, table) == watts
    # Strictly increasing: more RPM never means less power on this curve.
    watts_by_rpm = [interpolate_rpm_to_watts(r, table) for r in range(1000, 3451, 50)]
    assert watts_by_rpm == sorted(watts_by_rpm)


def test_ig1_ig2_have_no_curve_yet():
    # Documents the current, intentional state (see const.py's comment on
    # RPM_POWER_TABLES) — this test is meant to start failing the day
    # someone adds real IG1/IG2 calibration data, as a reminder to also
    # update this test (and the README's "Contribuer"/"Contribute"
    # section) rather than silently drifting out of sync.
    assert RPM_POWER_TABLES["IG1"] is None
    assert RPM_POWER_TABLES["IG2"] is None


# ---------------------------------------------------------------------------
# is_valid_status_result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, False),
        ({}, False),
        ({"dps": {}}, False),  # dps present but empty -- still not usable
        ({"dps": {"1": True}}, True),
        ({"dps": {"1": True}, "Error": "boom", "Err": "905"}, False),
        ({"Error": "Check device key or version", "Err": "914", "Payload": None}, False),
        ({"other_key": "x"}, False),  # no "dps" at all
    ],
)
def test_is_valid_status_result(result, expected):
    assert is_valid_status_result(result) is expected


# ---------------------------------------------------------------------------
# is_key_error_result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (None, False),
        ({}, False),
        ({"dps": {"1": True}}, False),  # a normal, successful result
        # ERR_OFFLINE / ERR_CONNECT / ERR_TIMEOUT -- network-level, NOT a
        # key error, must never trigger reauth.
        ({"Error": "Network Error: Device Unreachable", "Err": "905"}, False),
        ({"Error": "Network Error: Unable to Connect", "Err": "901"}, False),
        ({"Error": "Timeout Waiting for Device", "Err": "902"}, False),
        # The real payload tinytuya returns for a rejected local_key --
        # see error_json(ERR_KEY_OR_VER) in tinytuya's error_helper.py.
        ({"Error": "Check device key or version", "Err": "914", "Payload": None}, True),
    ],
)
def test_is_key_error_result(result, expected):
    assert is_key_error_result(result) is expected


# ---------------------------------------------------------------------------
# pick_reauth_default_device
# ---------------------------------------------------------------------------

DEVICES = {
    "dev-a": {"name": "Pool Pump", "local_key": "k1", "ip": ""},
    "dev-b": {"name": "Spa Pump", "local_key": "k2", "ip": ""},
}


def test_pick_reauth_default_device_prefers_matching_id():
    assert pick_reauth_default_device(DEVICES, "dev-b") == "dev-b"


def test_pick_reauth_default_device_falls_back_when_id_missing():
    # The originally-configured device_id is no longer in the account's
    # device list (e.g. a full delete + re-pair, not just a local_key
    # rotation) -- falls back to the same "first device" default a fresh
    # setup gets, instead of raising or defaulting to nothing.
    assert pick_reauth_default_device(DEVICES, "dev-does-not-exist") == next(iter(DEVICES))


def test_pick_reauth_default_device_plain_setup_picks_first():
    # reauth_device_id=None is what a fresh (non-reauth) setup passes.
    assert pick_reauth_default_device(DEVICES, None) == next(iter(DEVICES))


def test_pick_reauth_default_device_empty_devices():
    assert pick_reauth_default_device({}, "dev-a") is None


# ---------------------------------------------------------------------------
# should_attempt_ip_rescan
# ---------------------------------------------------------------------------

AFTER_FAILURES = 10
COOLDOWN = 300


def test_should_rescan_never_succeeded_always_scans():
    # A fresh coordinator (or reload) that hasn't managed a single
    # successful poll yet -- there's no "consecutive failures" run to
    # threshold against, so this fires on the very first failed attempt.
    assert should_attempt_ip_rescan(
        has_ever_succeeded=False,
        consecutive_offline_failures=0,
        seconds_since_last_rescan_attempt=None,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is True


def test_should_rescan_never_succeeded_ignores_cooldown():
    # Even a rescan attempted a second ago doesn't block the next one in
    # this branch -- HA's own ConfigEntryNotReady setup-retry backoff is
    # what paces this, not this function.
    assert should_attempt_ip_rescan(
        has_ever_succeeded=False,
        consecutive_offline_failures=0,
        seconds_since_last_rescan_attempt=1.0,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is True


def test_should_rescan_previously_working_below_failure_threshold():
    # A brief blip (fewer than after_failures consecutive misses) must not
    # trigger a scan.
    assert should_attempt_ip_rescan(
        has_ever_succeeded=True,
        consecutive_offline_failures=AFTER_FAILURES - 1,
        seconds_since_last_rescan_attempt=None,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is False


def test_should_rescan_previously_working_at_threshold_first_attempt():
    # Hits the threshold with no prior rescan attempt recorded yet -- scans.
    assert should_attempt_ip_rescan(
        has_ever_succeeded=True,
        consecutive_offline_failures=AFTER_FAILURES,
        seconds_since_last_rescan_attempt=None,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is True


def test_should_rescan_previously_working_within_cooldown_blocked():
    # Past the failure threshold, but the last rescan attempt was too
    # recent -- an extended outage must not scan every single cycle.
    assert should_attempt_ip_rescan(
        has_ever_succeeded=True,
        consecutive_offline_failures=AFTER_FAILURES + 5,
        seconds_since_last_rescan_attempt=COOLDOWN - 1,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is False


def test_should_rescan_previously_working_after_cooldown_elapsed():
    assert should_attempt_ip_rescan(
        has_ever_succeeded=True,
        consecutive_offline_failures=AFTER_FAILURES + 5,
        seconds_since_last_rescan_attempt=COOLDOWN + 1,
        after_failures=AFTER_FAILURES,
        cooldown_seconds=COOLDOWN,
    ) is True
