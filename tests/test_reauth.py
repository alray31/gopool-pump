"""Tests for the reauth flow (config_flow.py) and the ConfigEntryAuthFailed
trigger it responds to (GoPoolCoordinator._async_update_data, __init__.py).

Unlike tests/test_logic.py, these genuinely need Home Assistant — they
exercise the coordinator and the config flow, both of which import
`homeassistant.*` at module level (see __init__.py / config_flow.py).

NOT executed inside the sandboxed environment these tests were written in
(installing `pytest-homeassistant-custom-component` there failed while
building an unrelated transitive dependency — see this repo's CI workflow,
.github/workflows/tests.yml, which is what actually runs this file: GitHub
Actions' runners install this exact harness successfully across countless
other HA custom integrations, this was a sandbox-specific build issue, not
a sign the dependency itself is broken). Written to the harness's
documented/standard conventions; run locally with:

    pip install pytest-homeassistant-custom-component
    pytest tests/ -v

before relying on it for a release, the same as any new test file.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.gopool_pump import GoPoolCoordinator
from custom_components.gopool_pump.config_flow import GoPoolPumpConfigFlow
from custom_components.gopool_pump.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_PUMP_MODEL,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

KEY_ERROR_RESULT = {"Error": "Check device key or version", "Err": "914", "Payload": None}

ENTRY_DATA = {
    "name": "Pool Pump",
    "ip": "192.168.1.50",
    CONF_DEVICE_ID: "dev-a",
    CONF_LOCAL_KEY: "old-local-key",
    CONF_PROTOCOL_VERSION: "3.5",
    CONF_PUMP_MODEL: "AG1",
}


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, unique_id="dev-a", data=dict(ENTRY_DATA))


async def test_coordinator_raises_auth_failed_on_confirmed_key_error(
    hass: HomeAssistant,
) -> None:
    """Two consecutive ERR_KEY_OR_VER responses -> ConfigEntryAuthFailed,
    not the "keep last known state" fallback and not a plain UpdateFailed.
    This is the trigger the reauth flow below depends on — see
    is_key_error_result() in logic.py for why 914 specifically means this.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = GoPoolCoordinator(hass, entry)
    coordinator.device = MagicMock()
    coordinator.device.status.return_value = KEY_ERROR_RESULT
    coordinator.device.close.return_value = None

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    # Confirmed on BOTH attempts (the retry-once-after-reconnect logic) --
    # a single flaky read must not be enough to trigger reauth.
    assert coordinator.device.status.call_count == 2


async def test_coordinator_does_not_confuse_offline_with_key_error(
    hass: HomeAssistant,
) -> None:
    """A plain "device unreachable" failure must keep using the existing
    retry / optimistic-fallback behavior, never ConfigEntryAuthFailed --
    reauth is for a rejected credential, not a network blip."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = GoPoolCoordinator(hass, entry)
    coordinator.device = MagicMock()
    coordinator.device.status.return_value = {
        "Error": "Network Error: Device Unreachable",
        "Err": "905",
    }
    coordinator.device.close.return_value = None

    # An offline failure also runs _maybe_heal_ip() (__init__.py), which --
    # unmocked -- would perform a real 8-second UDP LAN scan via
    # scan_for_lan_ips (discovery.py). Patched out here for the same
    # reason the config-flow tests patch it: this test is only about
    # is_key_error_result's classification, not IP self-healing.
    with (
        patch(
            "custom_components.gopool_pump.scan_for_lan_ips",
            return_value={},
        ),
        pytest.raises(Exception) as exc_info,
    ):
        await coordinator._async_update_data()
    assert not isinstance(exc_info.value, ConfigEntryAuthFailed)


async def test_async_step_reauth_delegates_to_user_step(hass: HomeAssistant) -> None:
    """async_step_reauth must land on the same "user" form a fresh setup
    shows (re-login is genuinely required either way -- see the module
    docstring in config_flow.py), and must remember which device_id is
    being reauthenticated."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"


async def test_pick_device_preselects_matching_device_id_on_reauth(
    hass: HomeAssistant,
) -> None:
    """White-box test of a single step in isolation: pre-populate the flow
    instance's internal device list (normally filled in by
    async_step_pick_device itself, after the user/scan steps) and confirm
    the form it renders defaults "device" to the entry's existing
    device_id -- see pick_reauth_default_device() in logic.py, exercised
    here through the real config-flow step rather than only directly.

    Reaches into the flow's name-mangled private attributes
    (`_GoPoolPumpConfigFlow__devices` etc.) rather than driving the whole
    user -> scan -> pick_device journey through mocked tuya_sharing calls
    — deliberately narrow, to test this step's defaulting logic without
    also having to fake out the QR polling background task.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)

    flow = GoPoolPumpConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_REAUTH, "entry_id": entry.entry_id}
    flow._reauth_device_id = "dev-a"
    setattr(
        flow,
        "_GoPoolPumpConfigFlow__devices",
        {
            "dev-a": {"name": "Pool Pump", "local_key": "new-local-key", "ip": ""},
            "dev-b": {"name": "Spa Pump", "local_key": "other-key", "ip": ""},
        },
    )
    setattr(flow, "_GoPoolPumpConfigFlow__discovered_ips", {})

    with patch(
        "custom_components.gopool_pump.config_flow.scan_for_lan_ips",
        return_value={},
    ):
        result = await flow.async_step_pick_device()

    assert result["type"] == "form"
    assert result["step_id"] == "pick_device"
    assert result["data_schema"]({})["device"] == "dev-a"
    assert result["data_schema"]({})["ip"] == entry.data["ip"]


async def test_pick_device_updates_existing_entry_on_successful_reauth(
    hass: HomeAssistant,
) -> None:
    """Submitting the "pick_device" form during a reauth flow must update
    the SAME config entry (new local_key, same device_id/unique_id) and
    reload it, not create a second entry for the same pump."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    flow = GoPoolPumpConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_REAUTH, "entry_id": entry.entry_id}
    flow._reauth_device_id = "dev-a"
    setattr(
        flow,
        "_GoPoolPumpConfigFlow__devices",
        {"dev-a": {"name": "Pool Pump", "local_key": "new-local-key", "ip": ""}},
    )
    setattr(flow, "_GoPoolPumpConfigFlow__discovered_ips", {})

    with (
        patch(
            "custom_components.gopool_pump.config_flow.scan_for_lan_ips",
            return_value={},
        ),
        patch(
            "custom_components.gopool_pump.config_flow._test_connection_sync",
            return_value=True,
        ),
    ):
        result = await flow.async_step_pick_device(
            {"device": "dev-a", "ip": "192.168.1.51", "pump_model": "AG1"}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_LOCAL_KEY] == "new-local-key"
    assert entry.data["ip"] == "192.168.1.51"
    assert entry.data[CONF_DEVICE_ID] == "dev-a"
    # Still the same entry, not a second one for the same pump.
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_reconfigure_updates_ip_on_successful_connection_test(
    hass: HomeAssistant,
) -> None:
    """The manual counterpart to IP self-healing (see
    test_maybe_heal_ip_updates_entry_on_new_ip_found below): submitting the
    Reconfigure form with a new IP that passes the connection test must
    update the SAME entry's "ip" and reload it -- local_key/device_id are
    untouched, unlike reauth."""
    entry = _make_entry()
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.gopool_pump.config_flow.scan_for_lan_ips",
            return_value={},
        ),
        patch(
            "custom_components.gopool_pump.config_flow._test_connection_sync",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )
        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ip": "192.168.1.99"}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ip"] == "192.168.1.99"
    assert entry.data[CONF_LOCAL_KEY] == "old-local-key"
    assert entry.data[CONF_DEVICE_ID] == "dev-a"


async def test_maybe_heal_ip_updates_entry_on_new_ip_found(
    hass: HomeAssistant,
) -> None:
    """A fresh coordinator (never had a successful poll -- self.data is
    None) scans for the pump on every call, per should_attempt_ip_rescan's
    has_ever_succeeded=False branch (see logic.py / test_logic.py for the
    pure decision logic itself). If the scan finds it at a different
    address, _maybe_heal_ip must persist that via async_update_entry --
    it never touches self.device directly; the entry's own update
    listener (registered in async_setup_entry) is what reloads the
    integration with a fresh coordinator afterward."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = GoPoolCoordinator(hass, entry)
    assert coordinator.data is None

    with patch(
        "custom_components.gopool_pump.scan_for_lan_ips",
        return_value={"dev-a": "192.168.1.77"},
    ):
        await coordinator._maybe_heal_ip()

    assert entry.data["ip"] == "192.168.1.77"


async def test_maybe_heal_ip_leaves_entry_alone_when_scan_finds_nothing(
    hass: HomeAssistant,
) -> None:
    """A scan that comes back empty (pump still unreachable) must not
    touch the entry -- nothing to reload to, and repeatedly reloading on
    every failed scan would just thrash the integration."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    coordinator = GoPoolCoordinator(hass, entry)

    with patch(
        "custom_components.gopool_pump.scan_for_lan_ips",
        return_value={},
    ):
        await coordinator._maybe_heal_ip()

    assert entry.data["ip"] == ENTRY_DATA["ip"]
