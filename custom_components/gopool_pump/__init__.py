"""The GoPool Variable Speed Pump integration.

100% local runtime: once the config entry exists (device_id + local_key +
ip + protocol version), nothing here ever talks to the Tuya Cloud again —
only tinytuya's local LAN protocol is used, on every poll.
"""

from __future__ import annotations

from datetime import timedelta
import logging

import tinytuya

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number"]


class GoPoolCoordinator(DataUpdateCoordinator[dict]):
    """Polls the pump locally via tinytuya and exposes its dps dict."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        # dev_type="device22": this pump's 22-char device_id needs it
        # explicitly (see config_flow.py's _test_connection_sync for why).
        self.device = tinytuya.OutletDevice(
            dev_id=entry.data[CONF_DEVICE_ID],
            address=entry.data["ip"],
            local_key=entry.data[CONF_LOCAL_KEY],
        )
        self.device.set_version(float(entry.data.get(CONF_PROTOCOL_VERSION, "3.5")))
        # Same 20s timeout as the config flow's connection test — this pump
        # sits behind a slow wifi bridge and the default 5s was too short.
        self.device.set_socketTimeout(20)
        self.device.set_socketPersistent(True)

    async def _async_update_data(self) -> dict:
        result = await self.hass.async_add_executor_job(self.device.status)
        if not result or "dps" not in result:
            raise UpdateFailed(f"No response from pump: {result}")
        return result["dps"]

    async def async_write_dp(self, dp_id: str, value) -> None:
        """Write a single DP locally and refresh state."""
        await self.hass.async_add_executor_job(self.device.set_value, dp_id, value)
        await self.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GoPool Pump from a config entry."""
    coordinator = GoPoolCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # noqa: BLE001 - surfaced to the user via ConfigEntryNotReady
        raise ConfigEntryNotReady(
            f"Could not reach the pump locally at {entry.data['ip']}: {err}"
        ) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
