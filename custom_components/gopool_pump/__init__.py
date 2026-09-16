"""The GoPool Variable Speed Pump integration.

100% local runtime: once the config entry exists (device_id + local_key +
ip + protocol version), nothing here ever talks to the Tuya Cloud again —
only tinytuya's local LAN protocol is used, on every poll.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import threading
import time

import tinytuya

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_PUMP_MODEL,
    DEFAULT_PUMP_MODEL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PUMP_MODEL_DESCRIPTIONS,
    TUYA_IP_RESCAN_AFTER_FAILURES,
    TUYA_IP_RESCAN_COOLDOWN,
)
from .discovery import scan_for_lan_ips
from .logic import is_key_error_result, is_valid_status_result, should_attempt_ip_rescan

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number", "select", "sensor"]


def pump_model_label(hass: HomeAssistant, pump_model: str) -> str:
    """"AG1" -> "AG1 (Above-ground pool, 1.5 HP)" / "... (Piscine hors-terre
    1.5 HP)" / "... (Piscina sobre el suelo, 1.5 HP)" / "AG1 (地上泳池，1.5
    HP)", picked from the running HA instance's configured language. Falls
    back to the bare code for a model/language with no description yet.

    Public (no leading underscore) and imported from config_flow.py too, to
    build the pump-model selector's option labels — see
    _pump_model_selector() there for why those are plain literal labels
    rather than going through HA's translation-key system: a SelectSelector
    translation_key requires every OPTION VALUE to itself be a valid
    translation key ([a-z0-9-_]+, lowercase only), and PUMP_MODELS' real
    values ("AG1", "IG1", "IG2") fail that — hassfest rejects it. Building
    the same label text here in Python for both the device card and the
    selector keeps them consistent without fighting that constraint.
    """
    language = (hass.config.language or "").lower()
    if language.startswith("fr"):
        lang_key = "fr"
    elif language.startswith("es"):
        lang_key = "es"
    elif language.startswith("zh"):
        lang_key = "zh"
    else:
        lang_key = "en"
    description = PUMP_MODEL_DESCRIPTIONS.get(pump_model, {}).get(lang_key)
    return f"{pump_model} ({description})" if description else pump_model


def device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    """Build the shared DeviceInfo for every entity of this config entry.

    Single source of truth (previously duplicated independently in each
    platform module — see git history) so a field added here reaches every
    entity's device page automatically.

    `configuration_url` surfaces the pump's LAN IP as a clickable "Visit"
    link (the link text itself is the IP). `model` shows which pump model
    is in effect (used to pick the RPM->W calibration curve for the Power
    Draw / Energy sensors — see RPM_POWER_TABLES in const.py) together with
    a plain-language description, e.g. "AG1 (Above-ground pool, 1.5 HP)".

    device_id and local_key are NOT here — they're their own diagnostic
    sensor entities instead (sensor.py), disabled by default so they don't
    show up (or start writing to the recorder) unless the user opts in.
    local_key is additionally reachable via "Download diagnostics"
    (diagnostics.py) without needing to enable anything.
    """
    ip = entry.data.get("ip", "")
    pump_model = entry.options.get(
        CONF_PUMP_MODEL, entry.data.get(CONF_PUMP_MODEL, DEFAULT_PUMP_MODEL)
    )
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
        name=entry.data.get("name", "GoPool Pump"),
        manufacturer="GoPiscine",
        model=pump_model_label(hass, pump_model),
        configuration_url=f"http://{ip}" if ip else None,
    )


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
        # See _maybe_heal_ip() below and should_attempt_ip_rescan() in
        # logic.py: tracks consecutive offline poll cycles (reset on any
        # successful poll) and when a rescan was last attempted, so
        # background IP self-healing can be paced instead of hammering the
        # LAN with a UDP scan every single failed cycle.
        self._consecutive_offline_failures: int = 0
        self._last_ip_rescan_attempt: float | None = None

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

    async def _maybe_heal_ip(self) -> None:
        """Best-effort: look for the pump at a new LAN IP after it stopped
        answering at the one stored in the config entry, and if found,
        update the entry so this integration keeps working without the
        user having to notice and use the manual Reconfigure flow
        (config_flow.py's async_step_reconfigure).

        Deliberately does NOT touch self.device / self.device.address, and
        does NOT retry the poll itself within this same cycle. It only
        detects a new IP and persists it via
        hass.config_entries.async_update_entry() — that alone is enough:
        async_setup_entry() already registers
        entry.add_update_listener(_async_update_listener), which reacts to
        ANY change to entry.data (this includes it) by reloading the
        entry, tearing down this coordinator and building a fresh one from
        the corrected data. Mutating self.device mid-flight instead would
        race against that reload for no benefit.

        Never raises — this always runs from within the offline-failure
        branch of _async_update_data, which already has its own fallback
        behavior (keep last known state / raise UpdateFailed) to fall
        through to regardless of whether healing found anything.
        """
        if not should_attempt_ip_rescan(
            has_ever_succeeded=self.data is not None,
            consecutive_offline_failures=self._consecutive_offline_failures,
            seconds_since_last_rescan_attempt=(
                None
                if self._last_ip_rescan_attempt is None
                else time.monotonic() - self._last_ip_rescan_attempt
            ),
            after_failures=TUYA_IP_RESCAN_AFTER_FAILURES,
            cooldown_seconds=TUYA_IP_RESCAN_COOLDOWN,
        ):
            return
        # Only stamped once this entry has succeeded at least once — see
        # should_attempt_ip_rescan()'s has_ever_succeeded=False branch:
        # a never-yet-successful entry gets a brand new coordinator (and so
        # a fresh _last_ip_rescan_attempt) on every setup retry already,
        # so there's no "every cycle forever" risk there to cool down.
        if self.data is not None:
            self._last_ip_rescan_attempt = time.monotonic()
        device_id = self.entry.data[CONF_DEVICE_ID]
        try:
            found = await self.hass.async_add_executor_job(scan_for_lan_ips, [device_id])
        except Exception:  # noqa: BLE001 - best-effort, never let this break polling
            _LOGGER.debug("IP rescan for %s failed", device_id, exc_info=True)
            return
        new_ip = found.get(device_id)
        current_ip = self.entry.data.get("ip")
        if not new_ip or new_ip == current_ip:
            return
        _LOGGER.warning(
            "Pump %s unreachable at %s -- found it at %s via a local network "
            "scan, updating the config entry automatically",
            device_id,
            current_ip,
            new_ip,
        )
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, "ip": new_ip}
        )

    async def _async_update_data(self) -> dict:
        result = await self._async_poll_once()
        if not is_valid_status_result(result):
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
        if not is_valid_status_result(result):
            if is_key_error_result(result):
                # Confirmed on BOTH attempts (not just a one-off busy-socket
                # blip that happens to look similar) — this isn't something
                # retrying can ever fix, and letting the "keep last known
                # state" fallback below mask it would leave the pump stuck
                # forever with no indication why. See is_key_error_result()
                # in logic.py for exactly what tinytuya returns here and
                # why. ConfigEntryAuthFailed is Home Assistant's own signal
                # for "the stored credentials are no longer valid" — the
                # coordinator (post-setup) and async_setup_entry (first
                # refresh) both let it propagate instead of catching it, so
                # HA automatically starts the reauth flow this integration
                # implements in config_flow.py (async_step_reauth), which
                # re-runs the same QR login to fetch the new local_key.
                # translation_domain/translation_key/translation_placeholders
                # (not just a plain message) so Home Assistant's frontend can
                # show this in the user's own language instead of always in
                # English — see exceptions.rejected_local_key in
                # strings.json / translations/*.json for the localized text.
                # The plain-English positional message stays as a fallback
                # for logs and any older frontend that doesn't resolve it.
                raise ConfigEntryAuthFailed(
                    f"Rejected local_key for the pump at {self.entry.data.get('ip')} — "
                    "it was likely removed and re-added in the Smart Life app",
                    translation_domain=DOMAIN,
                    translation_key="rejected_local_key",
                    translation_placeholders={
                        "ip": str(self.entry.data.get("ip"))
                    },
                )
            # Plain connectivity failure (offline/timeout/wrong IP), not a
            # rejected key. Count it and give the background self-healer a
            # chance to find the pump at a new IP — see _maybe_heal_ip()
            # and should_attempt_ip_rescan() in logic.py for the pacing
            # policy (never on a single blip; throttled afterwards).
            self._consecutive_offline_failures += 1
            await self._maybe_heal_ip()
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
        self._consecutive_offline_failures = 0
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
    except ConfigEntryAuthFailed:
        # DataUpdateCoordinator.async_config_entry_first_refresh() (called
        # with raise_on_auth_failed=True internally) re-raises this as-is
        # rather than wrapping it into ConfigEntryNotReady — verified
        # against Home Assistant core's own update_coordinator.py. Must
        # NOT be caught by the blanket `except Exception` below: doing so
        # would silently convert it into an endless-retry ConfigEntryNotReady
        # loop instead of the reauth flow Home Assistant starts automatically
        # when this propagates out of async_setup_entry unmodified.
        raise
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
