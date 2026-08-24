"""Switch platform for GoPool Variable Speed Pump."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator
from .const import CONF_DEVICE_ID, DOMAIN, DP_MAP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GoPoolSwitch(coordinator, entry, dp_id, spec)
        for dp_id, spec in DP_MAP.items()
        if spec["platform"] == "switch"
    ]
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
            name=entry.data.get("name", "GoPool Pump"),
            manufacturer="GoPiscine",
        )

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(self._dp_id)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_write_dp(self._dp_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_write_dp(self._dp_id, False)
