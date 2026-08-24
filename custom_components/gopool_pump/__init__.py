"""The GoPool Variable Speed Pump integration.

100% local runtime: once the config entry exists (device_id + local_key +
ip + protocol version), nothing here ever talks to the Tuya Cloud again —
only tinytuya's local LAN protocol is used, on every poll.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import threading

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

PLATFORMS = ["switch", "number", "select", "sensor"]


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
        # tinytuya's Device/socket object isn't thread-safe. Executor jobs
        # run on HA's shared worker thread pool, so a scheduled poll
        # (status()) and a write triggered by the user touching an entity
        # (set_value()/set_multiple_values(), or that write's own follow-up
        # refresh) can end up on two different threads at once, both
        # talking to the same persistent socket — that's a genuine data
        # race, not just a "device is briefly busy" situation, and it can
        # corrupt both operations badly enough that even the retry-once
        # logic below fails. Every blocking call to self.device goes
        # through this lock so at most one is ever in flight.
        self._device_lock = threading.Lock()
        # tinytuya's status() doesn't always return every DP — right after
        # a set command (ours or an external one, e.g. Smart Life), the
        # device commonly answers with a "delta" response containing only
        # the DP(s) that just changed, not the full ~23-key set. Returning
        # that partial dict as-is used to REPLACE self.data wholesale,
        # which wiped out every other DP for one poll cycle — exactly the
        # "everything but the entity I just changed goes unavailable for a
        # few seconds" symptom. This cache is updated incrementally
        # (merged, never replaced) so a partial response only ever adds to
        # what's already known instead of blanking it.
        self._dps_cache: dict[str, object] = {}

    def _sync_status(self) -> dict | None:
        with self._device_lock:
            return self.device.status()

    def _sync_close(self) -> None:
        with self._device_lock:
            self.device.close()

    def _sync_set_value(self, dp_id: str, value) -> None:
        with self._device_lock:
            self.device.set_value(dp_id, value)

    def _sync_set_multiple_values(self, values: dict[str, object]) -> None:
        with self._device_lock:
            self.device.set_multiple_values(values)

    async def _async_poll_once(self) -> dict | None:
        """Read status() once, never letting an exception escape.

        tinytuya doesn't always fail politely with an error dict — a
        socket reset (e.g. another local client such as localTuya briefly
        taking over the pump's single local session) can raise instead of
        returning one. An uncaught exception here would propagate out of
        _async_update_data and make the coordinator set
        last_update_success = False, which greys out every entity — the
        exact flicker this is meant to prevent. Treat a raise exactly like
        a falsy/error result so the retry + optimistic-fallback logic below
        always gets a chance to run.
        """
        try:
            return await self.hass.async_add_executor_job(self._sync_status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("status() raised %s", err)
            return None

    @staticmethod
    def _is_valid_result(result: dict | None) -> bool:
        """True only for a genuinely usable status() response.

        tinytuya doesn't only fail by returning a falsy value or omitting
        "dps" entirely — a busy/contended socket (see the lock above for
        why that still happens occasionally, e.g. right after the pump's
        wifi module resets its local session following an external write)
        can come back as something like {"Error": "...", "Err": "905",
        "dps": {}}: a dict, with a "dps" key, that's still not usable data.
        Accepting that as a "successful" poll used to overwrite the
        coordinator's last known good state with an empty dict, which is
        what actually caused entities to flash unavailable/blank even
        after the thread-safety fix — not a failed poll at all, but a
        *falsely accepted* one.
        """
        return bool(result) and bool(result.get("dps")) and not result.get("Error")

    async def _async_update_data(self) -> dict:
        result = await self._async_poll_once()
        if not self._is_valid_result(result):
            # A single failed read is common right after something else
            # (the physical pump controls, the Smart Life app, or another
            # local client such as localTuya if it's still configured on
            # this same pump — most Tuya wifi modules only really like one
            # local session at a time) talks to the pump. Force a fresh
            # connection and retry once before giving up on this cycle.
            _LOGGER.debug("First status() read failed (%s) — reconnecting and retrying once", result)
            try:
                await self.hass.async_add_executor_job(self._sync_close)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("close() raised %s", err)
            result = await self._async_poll_once()
        if not self._is_valid_result(result):
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
        # Merge, don't replace: a "delta" response containing only the
        # DP(s) that just changed must not erase every other DP we already
        # know — see the comment on self._dps_cache above.
        self._dps_cache.update(result["dps"])
        return dict(self._dps_cache)

    async def async_write_dp(self, dp_id: str, value) -> None:
        """Write a single DP locally and refresh state."""
        await self.hass.async_add_executor_job(self._sync_set_value, dp_id, value)
        await self.async_request_refresh()

    async def async_write_dps(self, values: dict[str, object]) -> None:
        """Write multiple DPs in a single local command and refresh state.

        Used for entities that combine more than one DP (e.g. a stage's
        start hour + start minute as one time picker) so both land in one
        request instead of two separate round trips.
        """
        await self.hass.async_add_executor_job(self._sync_set_multiple_values, values)
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
    # Reload the entry when options change (currently just the pump model,
    # set via the options flow in config_flow.py) so the Power/Energy
    # sensors pick up the new RPM->W calibration curve immediately.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
