"""Switch platform for GoPool Variable Speed Pump."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator, device_info
from .const import CONF_DEVICE_ID, DOMAIN, DP_MAP


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


class GoPoolWinterizedSwitch(CoordinatorEntity[GoPoolCoordinator], RestoreEntity, SwitchEntity):
    """Local-only switch — NOT backed by any pump DP, unlike GoPoolSwitch
    above. Nothing is ever sent to the pump for this; it only flips
    coordinator.winterized (see its docstring in __init__.py), which
    makes GoPoolCoordinator._async_update_data skip polling entirely.

    Meant for the roughly 6 months a year this pump line's Canadian
    owners typically have it unplugged and winterized (see README) —
    without this, the coordinator keeps polling an intentionally
    unreachable pump every few seconds for months and logging a failure
    each time.

    RestoreEntity persists the on/off state itself across Home Assistant
    restarts, since there's no DP to read it back from — see
    coordinator.winterized's docstring for the one-poll-per-restart gap
    this implies before the restored value takes effect.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake"

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Winterized"
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_winterized"
        self._attr_device_info = device_info(coordinator.hass, entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self.coordinator.winterized = last_state.state == "on"
            self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.winterized

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.winterized = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.winterized = False
        self.async_write_ha_state()
        # Don't wait up to DEFAULT_SCAN_INTERVAL seconds for the next
        # scheduled cycle to find out the pump is reachable again.
        await self.coordinator.async_request_refresh()
