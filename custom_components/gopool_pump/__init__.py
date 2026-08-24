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

PLATFORMS = ["switch", "number", "select"]


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
        # No dev_type override: forcing "device22" produced inconsistent
        # Tuya-level errors even with confirmed-correct credentials (see
        # config_flow.py's _test_connection_sync for the diagnostic
        # history) — left as the library default, matching localTuya.
        self.device = tinytuya.OutletDevice(
            dev_id=entry.data[CONF_DEVICE_ID],
            address=entry.data["ip"],
            local_key=entry.data[CONF_LOCAL_KEY],
        )
        self.device.set_version(float(entry.data.get(CONF_PROTOCOL_VERSION, "3.5")))
        # A raw TCP connect to this pump measured 0.06s once the real bug
        # (dev_type="device22") was removed — 8s is generous headroom over
        # that, not the 20s used while we still thought the network itself
        # was slow.
        self.device.set_socketTimeout(8)
        self.device.set_socketPersistent(True)

    async def _async_update_data(self) -> dict:
        result = await self.hass.async_add_executor_job(self.device.status)
        if not result or "dps" not in result:
            # A single failed read is common right after something else
            # (the physical pump controls, the Smart Life app, or another
            # local client such as localTuya if it's still configured on
            # this same pump — most Tuya wifi modules only really like one
            # local session at a time) talks to the pump. Force a fresh
            # connection and retry once before giving up on this cycle.
            _LOGGER.debug("First status() read failed (%s) — reconnecting and retrying once", result)
            await self.hass.async_add_executor_job(self.device.close)
            result = await self.hass.async_add_executor_job(self.device.status)
        if not result or "dps" not in result:
            if self.data is not None:
                # Optimistic: keep serving the last known state instead of
                # raising UpdateFailed, which would grey out every entity.
                # A transient miss is common and self-corrects next cycle;
                # only the very first refresh (no prior data yet) still
                # raises below, so setup properly fails if the pump was
                # never reachable at all.
                _LOGGER.warning(
                    "Poll failed (%s) — keeping last known state instead of going unavailable",
                    result,
                )
                return self.data
            raise UpdateFailed(f"No response from pump: {result}")
        return result["dps"]

    async def async_write_dp(self, dp_id: str, value) -> None:
        """Write a single DP locally and refresh state."""
        await self.hass.async_add_executor_job(self.device.set_value, dp_id, value)
        await self.async_request_refresh()

    async def async_write_dps(self, values: dict[str, object]) -> None:
        """Write multiple DPs in a single local command and refresh state.

        Used for entities that combine more than one DP (e.g. a stage's
        start hour + start minute as one time picker) so both land in one
        request instead of two separate round trips.
        """
        await self.hass.async_add_executor_job(self.device.set_multiple_values, values)
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
