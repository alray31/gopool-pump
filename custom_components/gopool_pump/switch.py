"""Switch platform for GoPool Variable Speed Pump."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator, device_info
from .const import CONF_DEVICE_ID, CONF_WINTERIZED, DOMAIN, DP_MAP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [
        GoPoolSwitch(coordinator, entry, dp_id, spec)
        for dp_id, spec in DP_MAP.items()
        if spec["platform"] == "switch"
    ]
    entities.append(GoPoolWinterizedSwitch(coordinator, entry))
    async_add_entities(entities)


class GoPoolSwitch(CoordinatorEntity[GoPoolCoordinator], SwitchEntity):
    """A single boolean DP exposed as a switch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry, dp_id: str, spec: dict) -> None:
        super().__init__(coordinator)
        self._dp_id = dp_id
        self._attr_name = spec["name"]
        self._attr_icon = spec.get("icon")
        self._attr_entity_category = (
            EntityCategory.CONFIG if spec.get("category") == "config" else None
        )
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{spec['key']}"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._dp_id)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_write_dp(self._dp_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_write_dp(self._dp_id, False)


class GoPoolWinterizedSwitch(CoordinatorEntity[GoPoolCoordinator], SwitchEntity):
    """Local-only switch — NOT backed by any pump DP, unlike GoPoolSwitch
    above. Nothing is ever sent to the pump for this; it only flips
    coordinator.winterized (see its docstring in __init__.py), which
    makes GoPoolCoordinator._async_update_data skip polling entirely.

    Meant for the roughly 6 months a year this pump line's Canadian
    owners typically have it unplugged and winterized (see README) —
    without this, the coordinator keeps polling an intentionally
    unreachable pump every few seconds for months and logging a failure
    each time (or, before this persisted to entry.options, could get the
    whole config entry stuck retrying ConfigEntryNotReady forever if a
    restart happened while winterized — see coordinator.winterized's
    docstring).

    Persists to entry.options (CONF_WINTERIZED) on every toggle rather
    than using RestoreEntity: GoPoolCoordinator reads entry.options at
    construction time, before this entity exists, so this is what lets
    async_setup_entry's first refresh honor it immediately instead of
    only from the next reload onward.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake"

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Winterized"
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_winterized"
        self._attr_device_info = device_info(coordinator.hass, entry)

    @property
    def is_on(self) -> bool:
        return self.coordinator.winterized

    async def _async_set(self, value: bool) -> None:
        self.coordinator.winterized = value
        self.coordinator.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, CONF_WINTERIZED: value}
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
        # Don't wait up to DEFAULT_SCAN_INTERVAL seconds for the next
        # scheduled cycle to find out the pump is reachable again.
        await self.coordinator.async_request_refresh()
