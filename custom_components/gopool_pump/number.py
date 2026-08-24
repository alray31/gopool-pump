"""Number platform for GoPool Variable Speed Pump."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import GoPoolCoordinator
from .const import CONF_DEVICE_ID, DOMAIN, DP_MAP


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    coordinator: GoPoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GoPoolNumber(coordinator, entry, dp_id, spec)
        for dp_id, spec in DP_MAP.items()
        if spec["platform"] == "number"
    ]
    async_add_entities(entities)


class GoPoolNumber(CoordinatorEntity[GoPoolCoordinator], NumberEntity):
    """A single numeric DP exposed as a number.

    Box input by default (matches the original localtuya template
    preference), except entities that opt into a slider via
    spec["mode"] == "slider" (currently just Pump Speed)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GoPoolCoordinator, entry: ConfigEntry, dp_id: str, spec: dict) -> None:
        super().__init__(coordinator)
        self._dp_id = dp_id
        self._attr_name = spec["name"]
        self._attr_icon = spec.get("icon")
        self._attr_native_unit_of_measurement = spec.get("unit")
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_mode = NumberMode.SLIDER if spec.get("mode") == "slider" else NumberMode.BOX
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
    def native_value(self) -> float | None:
        value = self.coordinator.data.get(self._dp_id)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_dp(self._dp_id, int(value))
